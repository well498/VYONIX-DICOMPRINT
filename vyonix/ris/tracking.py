"""Central de exames (RIS): o ciclo de cada pedido numa linha — pedido → agendado → chegada → em realização →
imagens no PACS → laudo em redação → laudo liberado (ou cancelado) — com atrasos e tempos de atendimento.

Somente leitura e só com dados da própria organização (RLS). Os prazos de laudo usam os mesmos da fila de telelaudo
(``report.queue.SLA_HOURS``); o atraso de aquisição considera a hora agendada + duração + 30 minutos de tolerância.
Os tempos são operacionais (registro do sistema), não indicadores clínicos validados.
"""

from __future__ import annotations

import statistics
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vyonix.clinical.models import Order, Patient, Procedure, Study
from vyonix.db.base import utcnow
from vyonix.ris.models import Schedule

BRT = timezone(timedelta(hours=-3))
STAGES = ("requested", "scheduled", "arrived", "in_progress", "images", "reporting", "reported", "cancelled")
GRACE = timedelta(minutes=30)


def _minutes(a: datetime | None, b: datetime | None) -> int | None:
    return None if a is None or b is None else max(0, int((b - a).total_seconds() // 60))


def exam_center(s: Session, *, date_from: date, date_to: date, modality: str | None = None, stage: str | None = None,
                late_only: bool = False, limit: int = 500, now: datetime | None = None) -> dict[str, Any]:
    from vyonix.pacs.models import PacsInstance, PacsStudy
    from vyonix.report.models import Report
    from vyonix.report.queue import SLA_HOURS
    from vyonix.ris.service import completeness
    now = now or utcnow()
    start = datetime.combine(date_from, time.min, tzinfo=BRT)
    end = datetime.combine(date_to, time.max, tzinfo=BRT)
    orders = list(s.execute(select(Order, Patient, Procedure).join(Patient, Patient.id == Order.patient_id)
                            .outerjoin(Procedure, Procedure.id == Order.procedure_id)
                            .where(Order.created_at <= end).order_by(Order.created_at.desc()).limit(5000)))
    ids = [o.id for o, _p, _pr in orders]
    sched: dict = {}
    for sc in s.execute(select(Schedule).where(Schedule.order_id.in_(ids)).order_by(Schedule.created_at)).scalars():
        cur = sched.get(sc.order_id)
        if cur is None or cur.status == "cancelled" or sc.status != "cancelled":
            sched[sc.order_id] = sc                                    # o agendamento vigente (o último não cancelado)
    studies: dict = {}
    for st in s.execute(select(Study).where(Study.order_id.in_(ids)).order_by(Study.created_at)).scalars():
        studies.setdefault(st.order_id, st)
    st_ids = [st.id for st in studies.values()]
    reports = {r.study_id: r for r in s.execute(select(Report).where(Report.study_id.in_(st_ids))).scalars()}
    uids = [st.study_instance_uid for st in studies.values()]
    counts = dict(s.execute(select(PacsStudy.study_uid, func.count(PacsInstance.id))
                            .join(PacsInstance, PacsInstance.study_id == PacsStudy.id)
                            .where(PacsStudy.study_uid.in_(uids)).group_by(PacsStudy.study_uid)).all())
    items, tat_img, tat_rep = [], [], []
    by_stage = dict.fromkeys(STAGES, 0)
    late_total = 0
    for o, p, pr in orders:
        sc, st = sched.get(o.id), studies.get(o.id)
        sched_cancelled = sc is not None and sc.status == "cancelled"
        if sched_cancelled:
            sc = None                                             # só agendamento cancelado: volta a ser pedido
        ref = sc.scheduled_at if sc is not None else o.created_at
        if not (start <= ref <= end):
            continue
        mod = (sc.modality if sc else None) or (st.modality if st else None) or (pr.modality if pr else None)
        if modality and (mod or "").upper() != modality.strip().upper():
            continue
        r = reports.get(st.id) if st else None
        if o.status == "cancelled":
            stg = "cancelled"
        elif r is not None and r.status == "final":
            stg = "reported"
        elif r is not None:
            stg = "reporting"
        elif st is not None:
            stg = "images"
        elif sc is not None and sc.status in ("in_progress", "arrived", "scheduled"):
            stg = sc.status
        else:
            stg = "requested"
        flags = []
        if stg in ("scheduled", "arrived", "in_progress") and now > sc.scheduled_at + timedelta(
                minutes=sc.duration_min) + GRACE:
            flags.append("late_acquisition")
        if stg in ("images", "reporting") and now > st.created_at + timedelta(hours=SLA_HOURS.get(o.priority, 48)):
            flags.append("late_report")
        img = completeness(s, sc) if sc is not None else None
        if img and img["received"] < img["expected"]:
            flags.append("incomplete_images")
        if sched_cancelled and stg == "requested":
            flags.append("schedule_cancelled")
        if stg == "requested" and o.priority in ("urgent", "stat") and now > o.created_at + timedelta(hours=1):
            flags.append("not_scheduled")
        t_img = _minutes(o.created_at, st.created_at if st else None)
        t_rep = _minutes(st.created_at if st else None, r.finalized_at if r is not None else None)
        if t_img is not None:
            tat_img.append(t_img)
        if t_rep is not None:
            tat_rep.append(t_rep)
        by_stage[stg] += 1                                   # totais do período (os filtros só restringem a lista)
        late_total += bool(flags)
        if (late_only and not flags) or (stage and stg != stage):
            continue
        if len(items) < limit:
            items.append({
                "order_id": str(o.id), "accession": o.accession, "priority": o.priority, "patient_name": p.name,
                "procedure": pr.name if pr else None, "modality": mod, "requester": o.requester, "stage": stg,
                "flags": flags, "requested_at": o.created_at.isoformat(),
                "scheduled_at": sc.scheduled_at.isoformat() if sc else None,
                "room": (sc.room or sc.station_aet) if sc else None, "mpps_status": sc.mpps_status if sc else None,
                "study_instance_uid": st.study_instance_uid if st else (sc.study_instance_uid if sc else None),
                "images": counts.get(st.study_instance_uid) if st else None, "images_check": img,
                "received_at": st.created_at.isoformat() if st else None,
                "report_id": str(r.id) if r is not None else None,
                "reported_at": r.finalized_at.isoformat() if r is not None and r.finalized_at else None,
                "critical": bool(r is not None and r.critical),
                "minutes_to_images": t_img, "minutes_to_report": t_rep})

    def med(xs: list[int]) -> int | None:
        return int(statistics.median(xs)) if xs else None
    return {"items": items, "by_stage": by_stage, "late": late_total, "total": sum(by_stage.values()),
            "median_minutes_to_images": med(tat_img), "median_minutes_to_report": med(tat_rep)}
