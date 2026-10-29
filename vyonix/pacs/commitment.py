"""Storage Commitment Push Model (SCP) do VYONIX PACS, servido pelo Q/R do Core.

O equipamento que enviou imagens pede (N-ACTION) que o PACS assuma a guarda de uma lista de instâncias. O VYONIX só
confirma uma instância se ela estiver no índice da organização, com a mesma classe SOP, e se o arquivo **relido do
motor** tiver o SHA-256 registrado na entrada (um registro no banco não basta). O resultado vai num N-EVENT-REPORT,
numa associação nova do VYONIX para o endereço e a porta cadastrados do equipamento (papel SCP negociado).

Só nós cadastrados com "envia imagens" pedem commitment. Sem dados de pacientes no histórico; auditoria do resultado.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

log = logging.getLogger("vyonix.pacs.commitment")

PUSH_MODEL = "1.2.840.10008.1.20.1"
PUSH_MODEL_INSTANCE = "1.2.840.10008.1.20.1.1"
NO_SUCH_INSTANCE = 0x0112
CLASS_INSTANCE_CONFLICT = 0x0119
PROCESSING_FAILURE = 0x0110


def evaluate(s: Session, backend, refs: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], list[tuple[str, str, int]]]:
    """``refs`` = [(classe SOP, SOP Instance UID)]. Devolve (confirmadas, falhas com motivo)."""
    from vyonix.pacs.models import PacsInstance
    ok: list[tuple[str, str]] = []
    bad: list[tuple[str, str, int]] = []
    found = {i.sop_uid: i for i in s.execute(select(PacsInstance).where(
        PacsInstance.sop_uid.in_([u for _c, u in refs]))).scalars()} if refs else {}
    for cls, sop in refs:
        it = found.get(sop)
        if it is None:
            bad.append((cls, sop, NO_SUCH_INSTANCE))
            continue
        if it.sop_class_uid != cls:
            bad.append((cls, sop, CLASS_INSTANCE_CONFLICT))
            continue
        try:
            data = backend.fetch(it.backend_id)
        except Exception:  # noqa: BLE001 - motor fora do ar ou arquivo ausente: não confirma
            bad.append((cls, sop, PROCESSING_FAILURE))
            continue
        if hashlib.sha256(data).hexdigest() != it.sha256:
            bad.append((cls, sop, PROCESSING_FAILURE))
            continue
        ok.append((cls, sop))
    return ok, bad


def report_dataset(transaction_uid: str, ok, bad):
    from pydicom.dataset import Dataset
    ds = Dataset()
    ds.TransactionUID = transaction_uid
    if ok:
        ds.ReferencedSOPSequence = []
        for cls, sop in ok:
            it = Dataset()
            it.ReferencedSOPClassUID, it.ReferencedSOPInstanceUID = cls, sop
            ds.ReferencedSOPSequence.append(it)
    if bad:
        ds.FailedSOPSequence = []
        for cls, sop, reason in bad:
            it = Dataset()
            it.ReferencedSOPClassUID, it.ReferencedSOPInstanceUID, it.FailureReason = cls, sop, reason
            ds.FailedSOPSequence.append(it)
    return ds


def send_report(*, host: str, port: int, called_ae: str, calling_ae: str, dataset, success: bool,
                timeout: float = 30.0) -> str | None:
    """Envia o N-EVENT-REPORT (1 = todas confirmadas, 2 = com falhas). Devolve o erro ou None."""
    from pynetdicom import AE, build_role
    ae = AE(ae_title=(calling_ae or "VYONIX_QR")[:16])
    ae.acse_timeout = ae.dimse_timeout = ae.network_timeout = timeout
    ae.add_requested_context(PUSH_MODEL)
    assoc = ae.associate(host, int(port), ae_title=called_ae,
                         ext_neg=[build_role(PUSH_MODEL, scu_role=False, scp_role=True)])
    if not assoc.is_established:
        return f"Equipamento {called_ae} em {host}:{port} não aceitou a associação para o resultado do commitment."
    try:
        status, _ = assoc.send_n_event_report(dataset, 1 if success else 2, PUSH_MODEL, PUSH_MODEL_INSTANCE)
        code = getattr(status, "Status", None)
        if code != 0x0000:
            return f"Equipamento respondeu ao N-EVENT-REPORT com {hex(code) if code is not None else 'sem resposta'}."
    finally:
        assoc.release()
    return None


def handle_request(plat, backend, *, tenant, calling: str, address: str | None, transaction_uid: str,
                   refs: list[tuple[str, str]], our_ae: str, sender=None) -> dict[str, Any]:
    """Avalia o pedido e envia o resultado ao equipamento (chamado numa thread depois da resposta ao N-ACTION)."""
    from vyonix.audit import service as audit
    from vyonix.pacs import nodes as dnodes
    from vyonix.pacs import service as pacs
    sender = sender or send_report
    with plat.db.session(tenant) as s:
        ok, bad = evaluate(s, backend, refs)
        node = pacs.node_for(s, calling, address=address, store=True)
        dest = (node.host, node.port) if node is not None and node.host and node.port else None
    err = None
    if dest is None:
        err = "Equipamento sem endereço e porta cadastrados para receber o resultado do commitment."
    else:
        try:
            err = sender(host=dest[0], port=dest[1], called_ae=calling, calling_ae=our_ae,
                         dataset=report_dataset(transaction_uid, ok, bad), success=not bad)
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
    with plat.db.session(tenant) as s:
        dnodes.record(s, direction="out", service="commit", outcome="failed" if err else "ok", calling_ae=our_ae,
                      called_ae=calling, address=f"{dest[0]}:{dest[1]}" if dest else address,
                      detail=err or f"Storage commitment: {len(ok)} confirmada(s), {len(bad)} falha(s)")
        audit.record(s, actor=f"dicom:{calling}", action="pacs.commitment", target_type="dicom",
                     details={"calling_ae": calling, "transaction_uid": transaction_uid, "requested": len(refs),
                              "committed": len(ok), "failed": len(bad), **({"error": err} if err else {})},
                     ip=address)
    return {"committed": len(ok), "failed": len(bad), "error": err}
