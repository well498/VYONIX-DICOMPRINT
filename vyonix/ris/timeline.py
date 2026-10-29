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


def priors(s: Session, study_id: uuid.UUID, *, limit: int = 30) -> dict[str, Any]:
    """Exames anteriores do mesmo paciente na instituição (mais recentes primeiro; mesma modalidade destacada), com
    situação do laudo e se as imagens estão no PACS — para comparação no laudo e na preparação. Índice local: não
    busca em PACS remotos."""
    from vyonix.clinical.models import Study
    from vyonix.pacs.models import PacsStudy
    from vyonix.report.models import Report
    st = s.get(Study, study_id)
    if st is None:
        raise NotFound("Estudo não encontrado.")
    if st.patient_id is None:
        return {"patient_linked": False, "items": []}
    rows = list(s.execute(select(Study).where(Study.patient_id == st.patient_id, Study.id != st.id)
                          .order_by(Study.study_date.desc().nulls_last(), Study.created_at.desc()).limit(limit)).scalars())
    uids = [r.study_instance_uid for r in rows]
    in_pacs = set(s.execute(select(PacsStudy.study_uid).where(PacsStudy.study_uid.in_(uids))).scalars()) if uids else set()
    reps = {r.study_id: r for r in s.execute(select(Report).where(Report.study_id.in_([x.id for x in rows]))).scalars()} \
        if rows else {}
    items = []
    for r in rows:
        rep = reps.get(r.id)
        items.append({"study_id": str(r.id), "study_date": r.study_date.isoformat() if r.study_date else None,
                      "modality": r.modality, "description": r.description, "accession": r.accession,
                      "same_modality": bool(r.modality and r.modality == st.modality),
                      "study_instance_uid": r.study_instance_uid if r.study_instance_uid in in_pacs else None,
                      "report": None if rep is None else {"id": str(rep.id), "status": rep.status,
                                                         "finalized_at": rep.finalized_at.isoformat()
                                                         if rep.finalized_at else None}})
    return {"patient_linked": True, "items": items}


def patient_history(s: Session, patient_id: uuid.UUID, *, scope=None, shared: set | None = None) -> dict[str, Any]:
    """Histórico do paciente na instituição, um item por exame (sem duplicar): estudos com pedido, agendamento,
    imagens no PACS, documentos (séries DOC/SR, anexos da preparação), situação do laudo e atendimento; pedidos ainda
    sem estudo (agendados, cancelados); atendimentos sem pedido. Mais recentes primeiro.

    ``scope``: escopo do médico (``report.queue.scope``); exame de unidade fora do vínculo aparece como **restrito**
    (data e modalidade, sem descrição, laudo, documentos nem acesso às imagens). Organização isolada por RLS.
    Não contém texto de laudo nem conteúdo de documentos."""
    from sqlalchemy import func
    from vyonix.clinical.models import Encounter, Order, Patient, Procedure, Study
    from vyonix.pacs.models import PacsSeries, PacsStudy
    from vyonix.report import queue
    from vyonix.report.models import Report
    from vyonix.ris.models import ExamAttachment, Schedule
    pt = s.get(Patient, patient_id)
    if pt is None:
        raise NotFound("Paciente não encontrado.")
    shared = shared or set()
    studies = list(s.execute(select(Study).where(Study.patient_id == pt.id)).scalars())
    orders = {o.id: o for o in s.execute(select(Order).where(Order.patient_id == pt.id)).scalars()}
    encs = {e.id: e for e in s.execute(select(Encounter).where(Encounter.patient_id == pt.id)).scalars()}
    procs = {p.id: p for p in s.execute(select(Procedure).where(
        Procedure.id.in_([o.procedure_id for o in orders.values() if o.procedure_id]))).scalars()} if orders else {}
    scheds: dict[uuid.UUID, list] = {}
    if orders:
        for sc_ in s.execute(select(Schedule).where(Schedule.order_id.in_(list(orders)))).scalars():
            scheds.setdefault(sc_.order_id, []).append(sc_)
    uids = [x.study_instance_uid for x in studies]
    pst = {p.study_uid: p for p in s.execute(select(PacsStudy).where(PacsStudy.study_uid.in_(uids))).scalars()} \
        if uids else {}
    series = {}
    if pst:
        for ser in s.execute(select(PacsSeries).where(PacsSeries.study_id.in_([p.id for p in pst.values()]))).scalars():
            series.setdefault(ser.study_id, []).append(ser)
    reports = {r.study_id: r for r in s.execute(select(Report).where(
        Report.study_id.in_([x.id for x in studies]))).scalars()} if studies else {}
    atts = dict(s.execute(select(ExamAttachment.study_id, func.count()).where(
        ExamAttachment.study_id.in_([x.id for x in studies])).group_by(ExamAttachment.study_id)).all()) if studies else {}

    def enc_of(o):
        e = encs.get(o.encounter_id) if o and o.encounter_id else None
        return {"number": e.number, "arrived_at": e.arrived_at.isoformat() if e.arrived_at else None,
                "status": e.status} if e else None

    items: list[dict[str, Any]] = []
    used_orders, used_encs = set(), set()
    for st in studies:
        o = orders.get(st.order_id) if st.order_id else None
        if o is None:                                      # estudo ligado ao pedido só pelo agendamento
            o = next((orders[oid] for oid, ss in scheds.items() if any(
                x.study_instance_uid == st.study_instance_uid for x in ss)), None)
        if o is not None:
            used_orders.add(o.id)
            if o.encounter_id:
                used_encs.add(o.encounter_id)
        when = st.study_date.isoformat() if st.study_date else st.created_at.date().isoformat()
        ok = queue.allowed(scope, st.site_id) or st.id in shared
        base = {"kind": "study", "date": when, "modality": st.modality, "study_id": str(st.id), "restricted": not ok}
        if not ok:
            items.append(base)
            continue
        ps = pst.get(st.study_instance_uid)
        sers = series.get(ps.id, []) if ps else []
        rep = reports.get(st.id)
        docs = [{"kind": "dicom", "modality": x.modality, "description": x.description}
                for x in sers if (x.modality or "").upper() in ("DOC", "SR", "OT", "PR", "KO")]
        items.append({**base, "description": st.description, "accession": st.accession,
                      "study_instance_uid": st.study_instance_uid if ps else None,
                      "images": {"series": len(sers)} if ps else None,
                      "procedure": procs[o.procedure_id].name if o and o.procedure_id in procs else None,
                      "requester": o.requester if o else None, "order_status": o.status if o else None,
                      "encounter": enc_of(o),
                      "report": None if rep is None else {
                          "id": str(rep.id), "status": rep.status, "critical": rep.critical,
                          "finalized_at": rep.finalized_at.isoformat() if rep.finalized_at else None,
                          "versions": rep.version},
                      "documents": docs + ([{"kind": "attachment", "count": atts[st.id]}] if atts.get(st.id) else [])})
    for o in orders.values():
        if o.id in used_orders:
            continue
        ss = sorted(scheds.get(o.id, []), key=lambda x: x.scheduled_at)
        if o.encounter_id:
            used_encs.add(o.encounter_id)
        first = ss[0] if ss else None
        items.append({"kind": "order", "date": (first.scheduled_at if first else o.created_at).date().isoformat(),
                      "modality": first.modality if first else None, "restricted": False,
                      "description": (procs[o.procedure_id].name if o.procedure_id in procs else None)
                      or (first.description if first else None), "accession": o.accession, "order_status": o.status,
                      "schedule": [{"at": x.scheduled_at.isoformat(), "status": x.status, "room": x.room} for x in ss],
                      "requester": o.requester, "encounter": enc_of(o)})
    for e in encs.values():
        if e.id in used_encs:
            continue
        items.append({"kind": "encounter", "date": (e.arrived_at or e.created_at).date().isoformat(),
                      "restricted": False, "encounter": {"number": e.number, "status": e.status,
                                                         "arrived_at": e.arrived_at.isoformat() if e.arrived_at else None}})
    items.sort(key=lambda x: x["date"], reverse=True)
    return {"patient": {"id": str(pt.id), "name": pt.name,
                        "birth_date": pt.birth_date.isoformat() if pt.birth_date else None, "sex": pt.sex,
                        "merged_into_id": str(pt.merged_into_id) if pt.merged_into_id else None},
            "counts": {"studies": sum(1 for x in items if x["kind"] == "study"),
                       "orders_without_study": sum(1 for x in items if x["kind"] == "order"),
                       "encounters_without_order": sum(1 for x in items if x["kind"] == "encounter")},
            "items": items}
