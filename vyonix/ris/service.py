"""RIS: agendamento de exames e Modality Worklist (MWL).

* ``schedule``: cria o passo de procedimento agendado de um pedido, com um Study Instance UID novo (raiz 2.25,
  derivada de UUID — única sem depender de raiz de organização) e um SPS ID curto.
* ``worklist``: o que cada modalidade deve fazer (filtros por data, modalidade, AE da estação e paciente).
* ``mwl_dataset``: a entrada da worklist no formato DICOM (atributos do Modality Worklist Information Model).
* Consumidor de ``pacs.study.received.v1``: estudo que chegou ao PACS com o UID agendado marca o agendamento como
  recebido (a conciliação pelo número de acesso continua no cadastro clínico).
"""

from __future__ import annotations

import secrets
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from vyonix.audit import service as audit
from vyonix.clinical.models import Order, Patient, Procedure
from vyonix.errors import Conflict, NotFound, ValidationFailed
from vyonix.events.bus import Bus, Event, publish
from vyonix.ris.models import STATUSES, Schedule

ISSUER_FOR_MWL = "DICOM"          # identificador preferido como Patient ID na worklist (se existir)


def _aet(v: str | None) -> str | None:
    t = (v or "").strip().upper()
    if not t:
        return None
    import re
    if not re.fullmatch(r"[A-Z0-9_\-. ]{1,16}", t):
        raise ValidationFailed("AE Title da estação inválido (até 16 caracteres).")
    return t


def schedule(s: Session, order_id: uuid.UUID, *, scheduled_at: datetime, modality: str | None = None,
             station_aet: str | None = None, room: str | None = None, description: str | None = None, actor: str,
             actor_id=None, ip=None) -> Schedule:
    from pydicom.uid import generate_uid
    o = s.get(Order, order_id)
    if o is None:
        raise NotFound("Pedido não encontrado.")
    if o.status in ("completed", "cancelled"):
        raise Conflict("Pedido concluído ou cancelado não pode ser agendado.")
    if scheduled_at.tzinfo is None:
        raise ValidationFailed("Informe a data e a hora com fuso horário.")
    proc = s.get(Procedure, o.procedure_id) if o.procedure_id else None
    mod = (modality or (proc.modality if proc else "") or "").strip().upper()
    if not mod or len(mod) > 16:
        raise ValidationFailed("Informe a modalidade (ex.: CT, MR, CR) ou cadastre-a no procedimento.")
    st = Schedule(order_id=o.id, sps_id=f"S{secrets.token_hex(7).upper()}", study_instance_uid=generate_uid(prefix=None),   # 2.25.<UUID> (PS3.5 B.2), sem raiz de terceiros
                  scheduled_at=scheduled_at, modality=mod, station_aet=_aet(station_aet),
                  room=(room or "").strip()[:64] or None,
                  description=((description or (proc.name if proc else "")) or "").strip()[:64] or None,
                  status="scheduled", created_by=actor[:120])
    s.add(st)
    if o.status == "requested":
        o.status = "scheduled"
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="ris.schedule.create", target_type="schedule",
                 target_id=st.id, details={"order_id": str(o.id), "modality": mod, "station_aet": st.station_aet,
                                           "scheduled_at": scheduled_at.isoformat()})
    publish(s, "ris.schedule.created.v1", {"schedule_id": str(st.id), "order_id": str(o.id)}, source="ris",
            subject_kind="schedule", subject_id=st.id)
    return st


def pending_orders(s: Session, *, limit: int = 200) -> list[dict[str, Any]]:
    """Pedidos ainda sem agendamento (situação "requested"), mais antigos primeiro, para a tela de agendamento."""
    rows = s.execute(select(Order, Patient, Procedure).join(Patient, Patient.id == Order.patient_id)
                     .outerjoin(Procedure, Procedure.id == Order.procedure_id)
                     .where(Order.status == "requested").order_by(Order.created_at).limit(min(limit, 500)))
    return [{"order_id": str(o.id), "accession": o.accession, "priority": o.priority, "patient_name": p.name,
             "procedure": proc.name if proc else None, "modality": proc.modality if proc else None,
             "created_at": o.created_at.isoformat()} for o, p, proc in rows]


def set_status(s: Session, schedule_id: uuid.UUID, status: str, *, actor: str, reason: str | None = None,
               actor_id=None, ip=None) -> Schedule:
    if status not in STATUSES:
        raise ValidationFailed(f"Situação inválida (use: {', '.join(STATUSES)}).")
    st = s.get(Schedule, schedule_id)
    if st is None:
        raise NotFound("Agendamento não encontrado.")
    if st.status in ("completed", "cancelled") and status != st.status:
        raise Conflict("Agendamento concluído ou cancelado não muda de situação.")
    if status == "cancelled" and not (reason or "").strip():
        raise ValidationFailed("Informe o motivo do cancelamento.")
    old, st.status = st.status, status
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="ris.schedule.status", target_type="schedule",
                 target_id=st.id, details={"from": old, "to": status, "reason": (reason or "")[:300] or None})
    return st


def worklist(s: Session, *, date_from: date | None = None, date_to: date | None = None, modality: str | None = None,
             station_aet: str | None = None, patient_id: str | None = None, patient_name: str | None = None,
             accession: str | None = None, include_done: bool = False, limit: int = 500,
             tz: timezone | None = None) -> list[dict[str, Any]]:
    """Entradas da worklist. As datas são do dia local da clínica (``tz``; padrão UTC−3)."""
    from vyonix.clinical.models import PatientIdentifier
    tz = tz or timezone(timedelta(hours=-3))
    q = (select(Schedule, Order, Patient).join(Order, Order.id == Schedule.order_id)
         .join(Patient, Patient.id == Order.patient_id))
    if not include_done:
        q = q.where(Schedule.status.in_(("scheduled", "in_progress")))
    if modality:
        q = q.where(Schedule.modality == modality.strip().upper())
    if station_aet:
        q = q.where(Schedule.station_aet == station_aet.strip().upper())
    if accession:
        q = q.where(Order.accession == accession.strip())
    if patient_name:
        pat = patient_name.replace("^", " ").replace("*", "%").replace("?", "_").strip()
        q = q.where(Patient.name.ilike(pat if "%" in pat or "_" in pat else pat + "%"))
    if date_from:
        q = q.where(Schedule.scheduled_at >= datetime.combine(date_from, time.min, tzinfo=tz))
    if date_to:
        q = q.where(Schedule.scheduled_at <= datetime.combine(date_to, time.max, tzinfo=tz))
    rows = list(s.execute(q.order_by(Schedule.scheduled_at).limit(min(limit, 1000))))
    out = []
    for st, o, p in rows:
        ids = list(s.execute(select(PatientIdentifier).where(PatientIdentifier.patient_id == p.id)
                             .order_by(PatientIdentifier.issuer)).scalars())
        pref = next((i for i in ids if i.issuer == ISSUER_FOR_MWL), ids[0] if ids else None)
        pid = pref.value if pref else str(p.id)[:16].upper()
        if patient_id and pid != patient_id.strip() and not any(i.value == patient_id.strip() for i in ids):
            continue
        local = st.scheduled_at.astimezone(tz)
        out.append({"schedule_id": str(st.id), "order_id": str(o.id), "sps_id": st.sps_id, "status": st.status,
                    "study_instance_uid": st.study_instance_uid, "accession": o.accession, "priority": o.priority,
                    "modality": st.modality, "station_aet": st.station_aet, "room": st.room,
                    "description": st.description, "requester": o.requester,
                    "scheduled_date": local.strftime("%Y%m%d"), "scheduled_time": local.strftime("%H%M%S"),
                    "scheduled_at": st.scheduled_at.isoformat(), "patient_id": pid,
                    "issuer": pref.issuer if pref else None, "patient_name": p.name,
                    "birth_date": p.birth_date.strftime("%Y%m%d") if p.birth_date else None, "sex": p.sex})
    return out


def _pn(name: str) -> str:
    """Nome no formato DICOM (Família^Nome) a partir do nome cadastrado ("Nome Sobrenome")."""
    parts = name.strip().split()
    if len(parts) < 2:
        return name.strip()
    return f"{parts[-1]}^{' '.join(parts[:-1])}"


def mwl_dataset(e: dict[str, Any]):
    """Entrada da worklist no Modality Worklist Information Model (PS3.4 K.6)."""
    from pydicom.dataset import Dataset
    ds = Dataset()
    ds.SpecificCharacterSet = "ISO_IR 192"
    ds.PatientName = _pn(e["patient_name"])
    ds.PatientID = e["patient_id"]
    if e.get("issuer"):
        ds.IssuerOfPatientID = e["issuer"]
    ds.PatientBirthDate = e.get("birth_date") or ""
    ds.PatientSex = e.get("sex") or ""
    ds.AccessionNumber = e.get("accession") or ""
    ds.StudyInstanceUID = e["study_instance_uid"]
    ds.RequestedProcedureID = (e.get("accession") or e["sps_id"])[:16]
    ds.RequestedProcedureDescription = e.get("description") or ""
    ds.RequestedProcedurePriority = {"stat": "STAT", "urgent": "HIGH"}.get(e.get("priority") or "", "ROUTINE")
    ds.ReferringPhysicianName = e.get("requester") or ""
    sps = Dataset()
    sps.Modality = e["modality"]
    sps.ScheduledStationAETitle = e.get("station_aet") or ""
    sps.ScheduledProcedureStepStartDate = e["scheduled_date"]
    sps.ScheduledProcedureStepStartTime = e["scheduled_time"]
    sps.ScheduledProcedureStepDescription = e.get("description") or ""
    sps.ScheduledProcedureStepID = e["sps_id"]
    sps.ScheduledStationName = e.get("room") or ""
    ds.ScheduledProcedureStepSequence = [sps]
    return ds


def register_consumers(bus: Bus) -> None:
    @bus.subscribe("pacs.study.received.v1", "ris.mark_received")
    def received(s: Session, ev: Event) -> None:
        from vyonix.pacs.models import PacsStudy
        st = s.get(PacsStudy, uuid.UUID(ev.data["study_id"]))
        if st is None:
            return
        sch = s.execute(select(Schedule).where(Schedule.tenant_id == ev.tenant_id,
                                               Schedule.study_instance_uid == st.study_uid)).scalar_one_or_none()
        if sch is None or sch.status in ("received", "completed", "cancelled"):
            return
        old, sch.status = sch.status, "received"
        s.flush()
        audit.record(s, actor="ris", action="ris.schedule.status", target_type="schedule", target_id=sch.id,
                     details={"from": old, "to": "received", "via": "pacs"}, tenant_id=ev.tenant_id)
