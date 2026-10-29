"""Encaminhamento de estudos (roteamento): regras automáticas por origem e modalidade, envio manual e fila com novas
tentativas — referência de maturidade: regras de exportação de arquivos PACS corporativos; implementação própria.

* **Regra:** estudo novo cuja estação/AE de origem e/ou modalidade combinam → um envio para o nó de destino.
* **Quando envia:** depois de encerrada a recepção (sem imagem nova por ``STABLE_AFTER_S``), para não mandar estudo
  pela metade.
* **Como envia:** C-STORE do VYONIX (AE do Q/R) para o nó com "recebe estudos" (endereço e porta cadastrados), na
  mesma organização. Cada imagem tem o SHA-256 conferido antes do envio; imagem que não confere não é enviada.
* **Falha:** novas tentativas em 5 min, 15 min, 1 h, 3 h e 12 h; depois fica "falhou" para o administrador
  reenviar. Histórico de conexões e auditoria em cada tentativa. Nada é apagado na origem.
"""

from __future__ import annotations

import hashlib
import io
import logging
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from vyonix.audit import service as audit
from vyonix.db.base import utcnow
from vyonix.errors import NotFound, ValidationFailed

log = logging.getLogger("vyonix.pacs.forward")
BACKOFF_MIN = (5, 15, 60, 180, 720)
INTERVAL_S = 30
BATCH = 10


def _rule_out(r, names: dict) -> dict[str, Any]:
    return {"id": str(r.id), "name": r.name, "enabled": r.enabled, "source": r.source, "modality": r.modality,
            "destination_node_id": str(r.destination_node_id), "destination": names.get(r.destination_node_id),
            "row_version": r.row_version}


def _node_names(s: Session) -> dict:
    from vyonix.pacs.models import PacsDicomNode
    return {n.id: n.name or n.ae_title for n in s.execute(select(PacsDicomNode)).scalars()}


def _destination(s: Session, node_id) -> Any:
    from vyonix.pacs.models import PacsDicomNode
    n = s.get(PacsDicomNode, uuid.UUID(str(node_id)))
    if n is None:
        raise ValidationFailed("Nó de destino não encontrado nesta organização.")
    if not n.can_receive or not n.host or not n.port:
        raise ValidationFailed(f"O nó {n.ae_title} não está cadastrado para receber estudos (marque “Recebe estudos” "
                               "e informe endereço e porta).")
    return n


def rules(s: Session) -> list[dict]:
    from vyonix.pacs.models import PacsForwardRule
    names = _node_names(s)
    return [_rule_out(r, names) for r in s.execute(select(PacsForwardRule).order_by(PacsForwardRule.name)).scalars()]


def save_rule(s: Session, *, name: str, destination_node_id, source: str | None = None, modality: str | None = None,
              enabled: bool = True, rule_id: uuid.UUID | None = None, actor: str, actor_id=None, ip=None) -> dict:
    from vyonix.pacs.models import PacsForwardRule
    nm = (name or "").strip()[:120]
    if not nm:
        raise ValidationFailed("Dê um nome à regra.")
    dest = _destination(s, destination_node_id)
    src = (source or "").strip().upper()[:16] or None
    mod = (modality or "").strip().upper()[:16] or None
    if rule_id:
        r = s.get(PacsForwardRule, rule_id)
        if r is None:
            raise NotFound("Regra não encontrada.")
        r.name, r.destination_node_id, r.source, r.modality, r.enabled = nm, dest.id, src, mod, bool(enabled)
        action = "pacs.forward_rule.update"
    else:
        r = PacsForwardRule(name=nm, destination_node_id=dest.id, source=src, modality=mod, enabled=bool(enabled),
                            created_by=actor[:120])
        s.add(r)
        action = "pacs.forward_rule.add"
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action=action, target_type="forward_rule", target_id=r.id,
                 details={"name": nm, "source": src, "modality": mod, "destination": dest.ae_title,
                          "enabled": r.enabled})
    return _rule_out(r, _node_names(s))


def remove_rule(s: Session, rule_id: uuid.UUID, *, actor: str, actor_id=None, ip=None) -> None:
    from vyonix.pacs.models import PacsForwardRule
    r = s.get(PacsForwardRule, rule_id)
    if r is None:
        raise NotFound("Regra não encontrada.")
    s.delete(r)
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="pacs.forward_rule.remove",
                 target_type="forward_rule", target_id=rule_id, details={"name": r.name})


def matches(rule, *, source: str | None, modalities: set[str]) -> bool:
    if not rule.enabled:
        return False
    if rule.source and (source or "").upper() != rule.source:
        return False
    if rule.modality and rule.modality not in modalities:
        return False
    return True


def _study_modalities(s: Session, study_id: uuid.UUID) -> set[str]:
    from vyonix.pacs.models import PacsSeries
    return {(m or "").upper() for m in s.execute(select(PacsSeries.modality).where(PacsSeries.study_id == study_id))
            .scalars() if m}


def enqueue_for_study(s: Session, study_id: uuid.UUID, *, modality: str | None = None) -> int:
    """Cria os envios das regras que combinam com o estudo recém-recebido (consumidor de pacs.study.received.v1)."""
    from vyonix.pacs.models import PacsForwardJob, PacsForwardRule, PacsStudy
    from vyonix.pacs.service import STABLE_AFTER_S
    st = s.get(PacsStudy, study_id)
    if st is None:
        return 0
    mods = _study_modalities(s, st.id) | ({modality.upper()} if modality else set())
    n = 0
    for r in s.execute(select(PacsForwardRule).where(PacsForwardRule.enabled.is_(True))).scalars():
        if not matches(r, source=st.source_ae, modalities=mods):
            continue
        if s.execute(select(PacsForwardJob.id).where(PacsForwardJob.rule_id == r.id,
                                                     PacsForwardJob.study_id == st.id)).first():
            continue
        s.add(PacsForwardJob(rule_id=r.id, study_id=st.id, destination_node_id=r.destination_node_id, status="queued",
                             attempts=0, next_attempt_at=utcnow() + timedelta(seconds=STABLE_AFTER_S),
                             requested_by=f"regra:{r.name}"[:120]))
        n += 1
    s.flush()
    return n


def request(s: Session, study_uid: str, destination_node_id, *, actor: str, actor_id=None, ip=None) -> dict:
    """Envio manual de um estudo a um nó (entra na mesma fila, sai na próxima rodada do serviço)."""
    from vyonix.pacs import service as pacs
    from vyonix.pacs.models import PacsForwardJob
    st = pacs.study(s, study_uid)
    dest = _destination(s, destination_node_id)
    j = PacsForwardJob(rule_id=None, study_id=st.id, destination_node_id=dest.id, status="queued", attempts=0,
                       next_attempt_at=utcnow(), requested_by=actor[:120])
    s.add(j)
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="pacs.forward.request", target_type="study",
                 target_id=st.id, details={"destination": dest.ae_title, "job_id": str(j.id)})
    return job_out(j, _node_names(s), {st.id: st})


def job_out(j, names: dict, studies: dict) -> dict[str, Any]:
    st = studies.get(j.study_id)
    return {"id": str(j.id), "status": j.status, "attempts": j.attempts, "next_attempt_at": j.next_attempt_at.isoformat(),
            "instances": j.instances, "sent": j.sent, "integrity_failures": j.integrity_failures,
            "last_error": j.last_error, "done_at": j.done_at.isoformat() if j.done_at else None,
            "requested_by": j.requested_by, "destination": names.get(j.destination_node_id),
            "study_uid": st.study_uid if st else None, "accession": st.accession if st else None,
            "created_at": j.created_at.isoformat()}


def jobs(s: Session, *, limit: int = 100) -> list[dict]:
    from vyonix.pacs.models import PacsForwardJob, PacsStudy
    rows = list(s.execute(select(PacsForwardJob).order_by(PacsForwardJob.created_at.desc()).limit(limit)).scalars())
    studies = {x.id: x for x in s.execute(select(PacsStudy).where(PacsStudy.id.in_({j.study_id for j in rows})))
               .scalars()} if rows else {}
    names = _node_names(s)
    return [job_out(j, names, studies) for j in rows]


def retry(s: Session, job_id: uuid.UUID, *, actor: str, actor_id=None, ip=None) -> dict:
    from vyonix.pacs.models import PacsForwardJob
    j = s.get(PacsForwardJob, job_id)
    if j is None:
        raise NotFound("Envio não encontrado.")
    j.status, j.next_attempt_at, j.attempts = "queued", utcnow(), 0
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="pacs.forward.retry", target_type="forward_job",
                 target_id=j.id, details={})
    return job_out(j, _node_names(s), {})


# --------------------------------------------------------------------------- execução (VyonixWorker)

def process_due(s: Session, backend, *, calling_ae: str, now=None, sender=None) -> dict[str, int]:
    """Executa os envios vencidos da organização da sessão."""
    from vyonix.pacs import nodes as dnodes
    from vyonix.pacs.models import PacsDicomNode, PacsForwardJob, PacsInstance, PacsStudy
    from vyonix.pacs.service import STABLE_AFTER_S
    now = now or utcnow()
    sender = sender or c_store
    out = {"done": 0, "retry": 0, "failed": 0, "waiting": 0}
    due = list(s.execute(select(PacsForwardJob).where(PacsForwardJob.status == "queued",
                                                      PacsForwardJob.next_attempt_at <= now)
                         .order_by(PacsForwardJob.next_attempt_at).limit(BATCH)).scalars())
    for j in due:
        st = s.get(PacsStudy, j.study_id)
        node = s.get(PacsDicomNode, j.destination_node_id)
        if st is None or node is None or not node.enabled or not node.can_receive or not node.host or not node.port:
            j.status, j.last_error = "failed", "Estudo ou destino indisponível (nó removido, desativado ou sem permissão)."
            out["failed"] += 1
            continue
        if st.last_received_at and (now - st.last_received_at).total_seconds() < STABLE_AFTER_S:
            j.next_attempt_at = st.last_received_at + timedelta(seconds=STABLE_AFTER_S)   # recepção em andamento
            out["waiting"] += 1
            continue
        refs = [(i.backend_id, i.sha256, i.sop_class_uid, i.transfer_syntax) for i in s.execute(
            select(PacsInstance).where(PacsInstance.study_id == st.id)).scalars()]
        j.attempts += 1
        try:
            sent, bad, err = sender(backend, refs, host=node.host, port=node.port, called_ae=node.ae_title,
                                    calling_ae=calling_ae)
        except Exception as exc:  # noqa: BLE001
            sent, bad, err = 0, 0, f"{type(exc).__name__}: {exc}"
        j.instances, j.sent, j.integrity_failures = len(refs), sent, bad
        if err is None and sent + bad == len(refs):
            j.status, j.done_at, j.last_error = "done", now, (None if not bad else
                                                               f"{bad} imagem(ns) com integridade violada não enviada(s)")
            out["done"] += 1
            dnodes.record(s, direction="out", service="store", outcome="ok", calling_ae=calling_ae,
                          called_ae=node.ae_title, address=f"{node.host}:{node.port}", node=node, count=max(1, sent))
        else:
            j.last_error = (err or "Envio incompleto")[:300]
            if j.attempts > len(BACKOFF_MIN):
                j.status = "failed"
                out["failed"] += 1
            else:
                j.next_attempt_at = now + timedelta(minutes=BACKOFF_MIN[j.attempts - 1])
                out["retry"] += 1
            dnodes.record(s, direction="out", service="store", outcome="failed", calling_ae=calling_ae,
                          called_ae=node.ae_title, address=f"{node.host}:{node.port}", detail=j.last_error, node=node)
        audit.record(s, actor="pacs-forward", action="pacs.forward.attempt", target_type="study", target_id=st.id,
                     details={"job_id": str(j.id), "destination": node.ae_title, "attempt": j.attempts,
                              "instances": len(refs), "sent": sent, "integrity_failures": bad, "status": j.status,
                              **({"error": j.last_error} if j.status != "done" else {})})
    s.flush()
    return out


def c_store(backend, refs, *, host: str, port: int, called_ae: str, calling_ae: str,
            timeout: float = 30.0) -> tuple[int, int, str | None]:
    """Envia as instâncias (backend_id, sha256, classe, sintaxe) por C-STORE. Devolve (enviadas, íntegras recusadas,
    erro). Imagem com SHA-256 divergente não é enviada."""
    from pydicom import dcmread
    from pynetdicom import AE
    from pynetdicom.presentation import build_context
    ae = AE(ae_title=(calling_ae or "VYONIX_QR")[:16])
    ae.acse_timeout = ae.dimse_timeout = ae.network_timeout = timeout
    ctx = sorted({(c, t) for _b, _h, c, t in refs})[:128]
    if not ctx:
        return 0, 0, None
    for c, t in ctx:
        ae.requested_contexts.append(build_context(c, t))
    assoc = ae.associate(host, int(port), ae_title=called_ae)
    if not assoc.is_established:
        return 0, 0, f"Destino {called_ae} em {host}:{port} não aceitou a associação."
    sent = bad = 0
    err = None
    try:
        for backend_id, sha, _c, _t in refs:
            data = backend.fetch(backend_id)
            if hashlib.sha256(data).hexdigest() != sha:
                bad += 1
                log.error("Encaminhamento: integridade não confere para %s; imagem não enviada", backend_id)
                continue
            status = assoc.send_c_store(dcmread(io.BytesIO(data)))
            code = getattr(status, "Status", None)
            if code is None or not (code == 0x0000 or (code & 0xF000) == 0xB000):
                err = f"Destino recusou uma imagem (status {hex(code) if code is not None else 'sem resposta'})."
                break
            sent += 1
    finally:
        if assoc.is_established:
            assoc.release()
    return sent, bad, err


class ForwardTask:
    """Tarefa periódica do VyonixWorker: executa os envios vencidos de cada organização com PACS habilitado."""
    __name__ = "pacs-forward"

    def __init__(self, plat) -> None:
        self.plat = plat

    def __call__(self) -> dict:
        from vyonix.modules import registry
        from vyonix.pacs import backend_for
        from vyonix.tenancy import service as tenancy
        backend = backend_for(self.plat)
        if backend is None:
            return {"skipped": "motor DICOM não configurado"}
        calling = self.plat.cfg.extra.get("pacs_qr_aet", "VYONIX_QR")
        total = {"done": 0, "retry": 0, "failed": 0, "waiting": 0}
        tenants = ([tenancy.resolve(self.plat.db, self.plat.cfg.default_organization)] if self.plat.edge
                   else tenancy.organizations_for_service(self.plat.db))
        for tid in [t for t in tenants if t]:
            try:
                with self.plat.db.session(tid) as s:
                    if not registry.is_enabled(s, "pacs"):
                        continue
                    for k, v in process_due(s, backend, calling_ae=calling).items():
                        total[k] += v
            except Exception:  # noqa: BLE001 - uma organização com erro não para as outras
                log.exception("Encaminhamento: falha ao processar a organização %s", tid)
        if total["done"] or total["failed"]:
            log.info("Encaminhamento: %(done)d enviado(s), %(retry)d a repetir, %(failed)d falha(s)", total)
        return total


def register_consumers(bus) -> None:
    @bus.subscribe("pacs.study.received.v1", "pacs.forward_enqueue")
    def received(s, ev) -> None:
        enqueue_for_study(s, uuid.UUID(ev.data["study_id"]), modality=ev.data.get("modality"))
