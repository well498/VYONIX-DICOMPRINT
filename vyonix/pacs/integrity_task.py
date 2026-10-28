"""Verificação contínua da integridade do armazenamento do PACS (serviço VyonixWorker).

Percorre as instâncias indexadas em lotes (``BATCH`` por execução, a cada ``INTERVAL_S``), relê cada arquivo do
motor e confere o SHA-256 registrado na entrada. Ao fim de uma volta completa recomeça do início: com o tempo,
todo o acervo é relido (detecta arquivo corrompido ou perdido no disco antes de alguém precisar dele).

* Nada é alterado ou apagado: instância com problema é **apenas registrada** — na auditoria
  (``pacs.integrity.failure``, com o SOP Instance UID e o motivo, sem dados do paciente) e no arquivo de estado
  ``<dados>/pacs/integrity.json`` (lido pelo monitoramento). A recuperação é pelo backup (``pacs-restore``).
* Modo edge (organização do servidor). Motor indisponível: tenta de novo no próximo ciclo.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("vyonix.pacs.integrity")
INTERVAL_S = 3600
BATCH = 500
MAX_LISTED = 50


def state_file(plat) -> Path:
    return Path(plat.cfg.data_dir) / "pacs" / "integrity.json"


def read_state(plat) -> dict[str, Any] | None:
    try:
        return json.loads(state_file(plat).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(plat, st: dict) -> None:
    f = state_file(plat)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, f)


class PacsIntegrityTask:
    __name__ = "pacs-integrity"

    def __init__(self, plat, *, batch: int = BATCH) -> None:
        self.plat, self.batch = plat, batch

    def __call__(self) -> dict:
        from sqlalchemy import select, tuple_
        from vyonix.audit import service as audit
        from vyonix.modules import registry
        from vyonix.pacs import backend_for
        from vyonix.pacs.backend import BackendUnavailable
        from vyonix.pacs.models import PacsInstance
        from vyonix.tenancy import service as tenancy
        if not self.plat.edge:
            return {"skipped": "modo cloud"}
        backend = backend_for(self.plat)
        if backend is None:
            return {"skipped": "motor DICOM não configurado"}
        tid = tenancy.resolve(self.plat.db, self.plat.cfg.default_organization)
        if tid is None:
            return {"skipped": "organização não encontrada"}
        st = read_state(self.plat) or {"cursor": None, "rounds": 0, "failures": []}
        checked, bad, good = 0, [], set()
        with self.plat.db.session(tid) as s:
            if not registry.is_enabled(s, "pacs"):
                return {"skipped": "módulo PACS não habilitado"}
            q = select(PacsInstance.created_at, PacsInstance.id, PacsInstance.sop_uid, PacsInstance.sha256,
                       PacsInstance.backend_id).order_by(PacsInstance.created_at, PacsInstance.id).limit(self.batch)
            if st.get("cursor"):
                c_at, c_id = st["cursor"]
                q = q.where(tuple_(PacsInstance.created_at, PacsInstance.id) >
                            tuple_(datetime.fromisoformat(c_at), uuid.UUID(c_id)))
            rows = list(s.execute(q))
            for created, iid, sop, sha, bid in rows:
                try:
                    ok = hashlib.sha256(backend.fetch(bid)).hexdigest() == sha
                    reason = None if ok else "conteúdo diferente do registrado na entrada"
                except FileNotFoundError:
                    ok, reason = False, "arquivo ausente no motor"
                except BackendUnavailable as exc:
                    log.warning("Verificação de integridade interrompida: motor indisponível (%s)", exc)
                    break
                checked += 1
                st["cursor"] = [created.isoformat(), str(iid)]
                if ok:
                    good.add(sop)
                else:
                    bad.append({"sop_uid": sop, "reason": reason})
                    audit.record(s, actor="verificação de integridade", action="pacs.integrity.failure",
                                 target_type="pacs_instance", target_id=iid, details={"sop_uid": sop, "reason": reason})
            if len(rows) < self.batch and checked == len(rows):
                st["cursor"] = None                                  # volta completa: recomeça do início
                st["rounds"] = int(st.get("rounds", 0)) + 1
                st["last_round_at"] = datetime.now().isoformat(timespec="seconds")
        prev = [f for f in st.get("failures", []) if f["sop_uid"] not in good]    # corrigidas (ex.: restauradas) saem
        known = {f["sop_uid"] for f in prev}
        st["failures"] = (prev + [b | {"at": datetime.now().isoformat(timespec="seconds")}
                                                     for b in bad if b["sop_uid"] not in known])[-MAX_LISTED:]
        st["last_run_at"] = datetime.now().isoformat(timespec="seconds")
        st["last_checked"] = checked
        _write(self.plat, st)
        if bad:
            log.error("Integridade do PACS: %d instância(s) com problema neste lote", len(bad))
        return {"checked": checked, "failures": len(bad), "round_complete": st["cursor"] is None}
