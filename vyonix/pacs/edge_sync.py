"""VYONIX Edge Sync — protótipo da ADR-0014 (PACS local + central na nuvem). **Desabilitado**: nenhuma tarefa do
Worker usa este módulo e não há transporte de rede real; os testes usam um central simulado.

* **Fila:** instâncias do índice local ainda sem linha em ``pacs.edge_sync`` entram como ``queued`` (comparação com
  o índice; não depende de evento, então nada se perde se o serviço cair).
* **Envio:** em lotes pelo ``CentralTransport``; antes de enviar, o arquivo é relido do motor local e o SHA-256 é
  conferido com o índice (``integrity`` se divergir: não sai do edge).
* **Resultado por instância:** ``stored``/``duplicate`` com o mesmo SHA-256 → ``synced``; ``conflict`` (o central tem
  outro conteúdo com o mesmo UID) → ``conflict`` para decisão humana; SHA-256 devolvido diferente → ``integrity``.
* **Sem conexão:** ``TransportUnavailable`` → todo o lote volta para a fila com espera crescente (1, 2, 5, 10, 30,
  60 min) e ``offline_since`` é registrado; a próxima rodada retoma de onde parou.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vyonix.db.base import utcnow

BACKOFF_MIN = (1, 2, 5, 10, 30, 60)
BATCH = 50


class TransportUnavailable(RuntimeError):
    """O central não respondeu (internet fora, DNS, TLS, tempo esgotado)."""


class CentralTransport(Protocol):
    def store(self, items: list[tuple[str, bytes]]) -> dict[str, tuple[str, str | None]]:
        """Envia [(SOP Instance UID, arquivo DICOM)]; devolve {SOP: (stored|duplicate|conflict|rejected, sha256)}."""


@dataclass
class SyncState:
    """Estado volátil do sincronizador (no Worker real ficaria no banco/arquivo de estado)."""
    offline_since: datetime | None = None
    last_success: datetime | None = None
    rounds: int = 0
    errors: list[str] = field(default_factory=list)


def enqueue_new(s: Session, *, limit: int = 5000, now=None) -> int:
    from vyonix.pacs.models import PacsEdgeSync, PacsInstance
    q = (select(PacsInstance.id).outerjoin(PacsEdgeSync, PacsEdgeSync.instance_id == PacsInstance.id)
         .where(PacsEdgeSync.id.is_(None)).limit(limit))
    ids = list(s.execute(q).scalars())
    now = now or utcnow()
    for iid in ids:
        s.add(PacsEdgeSync(instance_id=iid, status="queued", attempts=0, next_attempt_at=now))
    s.flush()
    return len(ids)


def sync_once(s: Session, backend, transport: CentralTransport, state: SyncState, *, now=None) -> dict[str, int]:
    """Uma rodada: enfileira o que é novo e envia um lote vencido."""
    from vyonix.pacs.models import PacsEdgeSync, PacsInstance
    now = now or utcnow()
    state.rounds += 1
    out = {"enqueued": enqueue_new(s, now=now), "synced": 0, "conflict": 0, "integrity": 0, "retry": 0}
    rows = list(s.execute(select(PacsEdgeSync, PacsInstance).join(PacsInstance, PacsInstance.id == PacsEdgeSync.instance_id)
                          .where(PacsEdgeSync.status == "queued", PacsEdgeSync.next_attempt_at <= now)
                          .order_by(PacsEdgeSync.next_attempt_at).limit(BATCH)).all())
    if not rows:
        return out
    items, by_sop = [], {}
    for row, inst in rows:
        try:
            data = backend.fetch(inst.backend_id)
        except FileNotFoundError:
            row.status, row.last_error = "integrity", "Arquivo ausente no armazenamento local."
            out["integrity"] += 1
            continue
        if hashlib.sha256(data).hexdigest() != inst.sha256:
            row.status, row.last_error = "integrity", "Integridade violada no armazenamento local; não enviado."
            out["integrity"] += 1
            continue
        items.append((inst.sop_uid, data))
        by_sop[inst.sop_uid] = (row, inst)
    if items:
        try:
            res = transport.store(items)
        except TransportUnavailable as exc:
            state.offline_since = state.offline_since or now
            state.errors = (state.errors + [str(exc)[:200]])[-10:]
            for row, _inst in by_sop.values():
                row.attempts += 1
                row.next_attempt_at = now + timedelta(minutes=BACKOFF_MIN[min(row.attempts, len(BACKOFF_MIN)) - 1])
                row.last_error = f"Sem conexão com o central: {str(exc)[:200]}"
                out["retry"] += 1
            s.flush()
            return out
        state.offline_since = None
        state.last_success = now
        for sop, (row, inst) in by_sop.items():
            status, sha = res.get(sop, ("rejected", None))
            if status in ("stored", "duplicate") and sha == inst.sha256:
                row.status, row.synced_at, row.remote_sha256, row.last_error = "synced", now, sha, None
                out["synced"] += 1
            elif status in ("stored", "duplicate"):
                row.status, row.remote_sha256 = "integrity", sha
                row.last_error = "O central guardou conteúdo com SHA-256 diferente do enviado."
                out["integrity"] += 1
            elif status == "conflict":
                row.status, row.last_error = "conflict", "O central já tem outro conteúdo com este SOP Instance UID."
                out["conflict"] += 1
            else:
                row.attempts += 1
                row.next_attempt_at = now + timedelta(minutes=BACKOFF_MIN[min(row.attempts, len(BACKOFF_MIN)) - 1])
                row.last_error = f"Recusado pelo central ({status})."
                out["retry"] += 1
    s.flush()
    return out


def stats(s: Session, state: SyncState | None = None) -> dict[str, Any]:
    from vyonix.pacs.models import PacsEdgeSync, PacsInstance
    counts = dict(s.execute(select(PacsEdgeSync.status, func.count()).group_by(PacsEdgeSync.status)).all())
    total = s.execute(select(func.count()).select_from(PacsInstance)).scalar() or 0
    oldest = s.execute(select(func.min(PacsEdgeSync.created_at)).where(PacsEdgeSync.status == "queued")).scalar()
    return {"instances": total, "not_enqueued": total - sum(counts.values()),
            "queued": counts.get("queued", 0), "synced": counts.get("synced", 0),
            "conflict": counts.get("conflict", 0), "integrity": counts.get("integrity", 0),
            "oldest_pending": oldest.isoformat() if oldest else None,
            "offline_since": state.offline_since.isoformat() if state and state.offline_since else None,
            "last_success": state.last_success.isoformat() if state and state.last_success else None}


class SimulatedCentral:
    """Central SIMULADO para testes: ingere numa organização do mesmo banco (sem rede). Pode "cair" (``down``).

    A organização de destino é fixa por instância do transporte, como o certificado de cliente do servidor edge
    no desenho da ADR-0014 — o edge não escolhe a organização."""

    def __init__(self, db, tenant: uuid.UUID, backend) -> None:
        self.db, self.tenant, self.backend = db, tenant, backend
        self.down = False
        self.calls = 0

    def store(self, items):
        from vyonix.pacs import service as pacs
        self.calls += 1
        if self.down:
            raise TransportUnavailable("tempo esgotado ao conectar ao central (simulado)")
        out = {}
        with self.db.session(self.tenant) as s:
            for sop, data in items:
                try:
                    with s.begin_nested():
                        r = pacs.ingest(s, self.backend, data, actor="edge-sync", via="stow")
                    out[sop] = ("duplicate" if r.duplicate else "stored", hashlib.sha256(data).hexdigest())
                except pacs.InstanceRejected as exc:
                    out[sop] = ("conflict" if exc.failure == pacs.FAIL_CONFLICT else "rejected", None)
        return out
