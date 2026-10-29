"""Linha do tempo do exame: cada etapa do fluxo (solicitação → agendamento → worklist/MPPS → aquisição → PACS → viewer
→ preparação → distribuição → laudo → liberação) com data e hora, responsável e detalhe, montada a partir dos
registros do próprio sistema (cadastros e trilha de auditoria). Somente leitura, só da organização da sessão.

Não contém o texto do laudo nem dos comentários (só o fato e quem fez).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from vyonix.errors import NotFound

LABELS: dict[str, tuple[str, str]] = {
    # ação de auditoria → (etapa, texto)
    "ris.schedule.create": ("scheduling", "Exame agendado"),
    "ris.mpps.create": ("acquisition", "Modalidade iniciou o exame (MPPS)"),
    "ris.mpps.set": ("acquisition", "Modalidade atualizou o exame (MPPS)"),
    "ris.mpps.unscheduled": ("acquisition", "Exame realizado sem agendamento (MPPS)"),
    "pacs.study.open": ("viewer", "Estudo aberto"),
    "ris.prep.check": ("preparation", "Checklist da preparação"),
    "ris.prep.comment": ("preparation", "Comentário registrado"),
    "ris.prep.attachment": ("preparation", "Anexo incluído"),
    "ris.prep.flag": ("preparation", "Suspeita técnica registrada"),
    "ris.prep.flag_resolved": ("preparation", "Suspeita técnica resolvida"),
    "ris.prep.duplicate": ("preparation", "Conferência de duplicidade"),
    "ris.prep.priority": ("preparation", "Prioridade alterada"),
    "ris.prep.forward": ("preparation", "Encaminhado para laudo"),
    "ris.prep.return": ("preparation", "Devolvido para correção"),
    "ris.prep.cancel": ("preparation", "Estudo cancelado"),
    "ris.prep.share": ("preparation", "Compartilhado temporariamente"),
    "report.assign": ("distribution", "Atribuído a médico"),
    "report.open": ("report", "Laudo iniciado"),
    "report.finalize": ("release", "Laudo liberado"),
    "report.addendum": ("release", "Adendo liberado"),
}
STATUS_TEXT = {"arrived": "Paciente chegou", "in_progress": "Exame em realização", "completed": "Exame concluído",
               "cancelled": "Agendamento cancelado", "received": "Imagens recebidas para o agendamento",
               "no_show": "Paciente não compareceu", "scheduled": "Agendado"}
STAGES = ("order", "scheduling", "acquisition", "pacs", "viewer", "preparation", "distribution", "report", "release")
STAGE_NAMES = {"order": "Solicitação", "scheduling": "Agendamento", "acquisition": "Aquisição", "pacs": "PACS",
               "viewer": "Viewer", "preparation": "Preparação", "distribution": "Distribuição", "report": "Laudo",
               "release": "Liberação"}


def _detail(action: str, d: dict) -> str | None:
    if action == "ris.schedule.status":
        return None
    if action == "ris.prep.check":
        return f"{d.get('item')}: {'marcado' if d.get('done') else 'desmarcado'}"
    if action == "ris.prep.return":
        return (d.get("reason") or "")[:200] or None
    if action == "ris.prep.priority":
        return d.get("priority")
    if action == "pacs.study.open":
        return {"viewer": "no Viewer", "dimse-move": "envio por C-MOVE", "dimse-get": "envio por C-GET"}.get(
            d.get("purpose"), d.get("purpose"))
    if action == "ris.mpps.set" or action == "ris.mpps.create":
        return d.get("status")
    if action == "report.finalize":
        return f"versão {d.get('version')}" if d.get("version") else None
    return None


def study_timeline(s: Session, study_id: uuid.UUID) -> dict[str, Any]:
    from vyonix.audit.models import AuditEntry
    from vyonix.clinical.models import Order, Study
    from vyonix.pacs.models import PacsStudy
    from vyonix.report.models import Report
    from vyonix.ris.models import Schedule
    st = s.get(Study, study_id)
    if st is None:
        raise NotFound("Estudo não encontrado.")
    ev: list[dict[str, Any]] = []
    order = s.get(Order, st.order_id) if st.order_id else None
    sch = s.execute(select(Schedule).where(Schedule.study_instance_uid == st.study_instance_uid)).scalar_one_or_none()
    if order is None and sch is not None:
        order = s.get(Order, sch.order_id)
    if order is not None:
        ev.append({"stage": "order", "at": order.created_at, "by": None, "text": "Pedido registrado",
                   "detail": order.requester})
    ps = s.execute(select(PacsStudy).where(PacsStudy.study_uid == st.study_instance_uid)).scalar_one_or_none()
    if ps is not None:
        ev.append({"stage": "pacs", "at": ps.created_at, "by": ps.source_ae, "text": "Primeiras imagens recebidas no PACS",
                   "detail": None})
        if ps.last_received_at and (ps.last_received_at - ps.created_at).total_seconds() > 60:
            ev.append({"stage": "pacs", "at": ps.last_received_at, "by": ps.source_ae,
                       "text": "Última imagem recebida", "detail": None})
    else:
        ev.append({"stage": "pacs", "at": st.created_at, "by": None, "text": "Estudo registrado", "detail": None})
    reports = list(s.execute(select(Report.id).where(Report.study_id == st.id)).scalars())
    targets = [str(st.id)] + ([str(sch.id)] if sch else []) + ([str(ps.id)] if ps else []) + [str(r) for r in reports]
    rows = s.execute(select(AuditEntry).where(AuditEntry.target_id.in_(targets), or_(
        AuditEntry.action.in_(list(LABELS)), AuditEntry.action == "ris.schedule.status"))
        .order_by(AuditEntry.seq)).scalars()
    for a in rows:
        d = a.details or {}
        if a.action == "ris.schedule.status":
            to = d.get("to")
            stage = "acquisition" if to in ("arrived", "in_progress", "completed", "received") else "scheduling"
            ev.append({"stage": stage, "at": a.at, "by": a.actor, "text": STATUS_TEXT.get(to, f"Situação: {to}"),
                       "detail": d.get("reason")})
            continue
        stage, text = LABELS[a.action]
        ev.append({"stage": stage, "at": a.at, "by": a.actor, "text": text, "detail": _detail(a.action, d)})
    ev.sort(key=lambda e: e["at"])
    reached = {e["stage"] for e in ev}
    current = next((x for x in reversed(STAGES) if x in reached), "pacs")
    return {"study_id": str(st.id), "current": current, "current_name": STAGE_NAMES[current],
            "stages": [{"code": c, "name": STAGE_NAMES[c], "done": c in reached} for c in STAGES],
            "events": [{**e, "at": e["at"].isoformat(), "stage_name": STAGE_NAMES[e["stage"]]} for e in ev]}
