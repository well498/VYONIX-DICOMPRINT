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

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vyonix.audit import service as audit
from vyonix.clinical.models import Order, Patient, Procedure
from vyonix.errors import Conflict, NotFound, ValidationFailed
from vyonix.events.bus import Bus, Event, publish
from vyonix.ris.models import STATUSES, Room, Schedule

ISSUER_FOR_MWL = "DICOM"          # identificador preferido como Patient ID na worklist (se existir)


def _aet(v: str | None) -> str | None:
    t = (v or "").strip().upper()
    if not t:
        return None
    import re
    if not re.fullmatch(r"[A-Z0-9_\-. ]{1,16}", t):
        raise ValidationFailed("AE Title da estação inválido (até 16 caracteres).")
    return t


ACTIVE = ("scheduled", "arrived", "in_progress")


def conflicts(s: Session, *, start: datetime, minutes: int, station_aet: str | None, room: str | None,
              exclude: uuid.UUID | None = None) -> list[Schedule]:
    """Agendamentos ativos na mesma estação ou sala cujo intervalo se sobrepõe a [start, start+minutes)."""
    from sqlalchemy import or_
    if not station_aet and not room:
        return []
    end = start + timedelta(minutes=minutes)
    same = []
    if station_aet:
        same.append(Schedule.station_aet == station_aet)
    if room:
        same.append(Schedule.room == room)
    q = select(Schedule).where(Schedule.status.in_(ACTIVE), or_(*same), Schedule.scheduled_at < end,
                               Schedule.scheduled_at > start - timedelta(hours=24))
    if exclude:
        q = q.where(Schedule.id != exclude)
    return [x for x in s.execute(q).scalars()
            if x.scheduled_at + timedelta(minutes=x.duration_min) > start]


def workflow(s: Session) -> dict[str, bool]:
    """Etapas do fluxo do exame configuradas pela instituição (``ris/workflow``)."""
    from vyonix.settings import service as settings
    return settings.get(s, "ris", "workflow")


def schedule(s: Session, order_id: uuid.UUID, *, scheduled_at: datetime, modality: str | None = None,
             station_aet: str | None = None, room: str | None = None, description: str | None = None,
             duration_min: int | None = None, actor: str, actor_id=None, ip=None) -> Schedule:
    from pydicom.uid import generate_uid
    if not workflow(s)["scheduling"]:
        raise ValidationFailed("O agendamento está desligado nesta instituição (Configurações → Fluxo do exame).")
    o = s.get(Order, order_id)
    if o is None:
        raise NotFound("Pedido não encontrado.")
    if o.status in ("completed", "cancelled"):
        raise Conflict("Pedido concluído ou cancelado não pode ser agendado.")
    if scheduled_at.tzinfo is None:
        raise ValidationFailed("Informe a data e a hora com fuso horário.")
    proc = s.get(Procedure, o.procedure_id) if o.procedure_id else None
    from sqlalchemy import func
    reg = s.execute(select(Room).where(func.lower(Room.name) == (room or "").strip().lower(),
                                       Room.active.is_(True))).scalar_one_or_none() if room else None
    if reg is not None:                         # sala cadastrada: nome padronizado e valores padrão da sala
        room = reg.name
        station_aet = station_aet or reg.station_aet
        modality = modality or reg.modality
        duration_min = reg.default_duration_min if duration_min is None else duration_min
    duration_min = 15 if duration_min is None else duration_min
    mod = (modality or (proc.modality if proc else "") or "").strip().upper()
    if not mod or len(mod) > 16:
        raise ValidationFailed("Informe a modalidade (ex.: CT, MR, CR) ou cadastre-a no procedimento.")
    if not 1 <= int(duration_min) <= 480:
        raise ValidationFailed("Duração do exame: de 1 a 480 minutos.")
    aet, room_n = _aet(station_aet), (room or "").strip()[:64] or None
    # serializa agendamentos da organização: duas recepções não reservam o mesmo horário ao mesmo tempo
    from sqlalchemy import text
    s.execute(text("SELECT pg_advisory_xact_lock(hashtext('ris.schedule:' || CAST(:t AS text)))"),
              {"t": str(o.tenant_id)})
    clash = conflicts(s, start=scheduled_at, minutes=int(duration_min), station_aet=aet, room=room_n)
    if clash:
        c = clash[0]
        where = f"estação {c.station_aet}" if aet and c.station_aet == aet else f"sala {c.room}"
        local = c.scheduled_at.astimezone(timezone(timedelta(hours=-3))).strftime("%d/%m %H:%M")
        raise Conflict(f"Horário ocupado na {where}: exame às {local} ({c.duration_min} min). Escolha outro horário.")
    st = Schedule(order_id=o.id, duration_min=int(duration_min), sps_id=f"S{secrets.token_hex(7).upper()}", study_instance_uid=generate_uid(prefix=None),   # 2.25.<UUID> (PS3.5 B.2), sem raiz de terceiros
                  scheduled_at=scheduled_at, modality=mod, station_aet=aet,
                  room=room_n,
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


def save_room(s: Session, *, name: str, modality: str | None = None, station_aet: str | None = None,
              default_duration_min: int = 15, active: bool = True, room_id: uuid.UUID | None = None, actor: str,
              actor_id=None, ip=None) -> Room:
    from sqlalchemy import func
    name = (name or "").strip()
    if not name or len(name) > 64:
        raise ValidationFailed("Nome da sala: 1 a 64 caracteres.")
    if not 1 <= int(default_duration_min) <= 480:
        raise ValidationFailed("Duração padrão: de 1 a 480 minutos.")
    r = s.get(Room, room_id) if room_id else None
    if room_id and r is None:
        raise NotFound("Sala não encontrada.")
    dup = s.execute(select(Room).where(func.lower(Room.name) == name.lower())).scalar_one_or_none()
    if dup is not None and dup is not r:
        raise Conflict("Já existe uma sala com esse nome.")
    if r is None:
        r = Room(name=name)
        s.add(r)
    r.name, r.modality = name, (modality or "").strip().upper()[:16] or None
    r.station_aet, r.default_duration_min, r.active = _aet(station_aet), int(default_duration_min), bool(active)
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="ris.room.save", target_type="room", target_id=r.id,
                 details={"name": r.name, "modality": r.modality, "station_aet": r.station_aet, "active": r.active})
    return r


def rooms(s: Session, *, include_inactive: bool = False) -> list[dict[str, Any]]:
    q = select(Room).order_by(Room.name)
    if not include_inactive:
        q = q.where(Room.active.is_(True))
    return [{"id": str(r.id), "name": r.name, "modality": r.modality, "station_aet": r.station_aet,
             "default_duration_min": r.default_duration_min, "active": r.active} for r in s.execute(q).scalars()]


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
    if status == "arrived":
        o = s.get(Order, st.order_id)
        if o is not None and o.status in ("requested", "scheduled"):
            o.status = "arrived"           # pedido acompanha o check-in (mesma situação do cadastro clínico)
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
        q = q.where(Schedule.status.in_(ACTIVE))
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
                    "modality": st.modality, "station_aet": st.station_aet, "room": st.room, "duration_min": st.duration_min,
                    "mpps_status": st.mpps_status, "images": completeness(s, st), "mpps_summary": st.mpps_summary,
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
    # (0040,0020) termos definidos na PS3.3 C.4.10
    sps.ScheduledProcedureStepStatus = {"arrived": "ARRIVED", "in_progress": "STARTED"}.get(e.get("status"), "SCHEDULED")
    ds.ScheduledProcedureStepSequence = [sps]
    return ds


# ------------------------------------------------------------------ MPPS (PS3.4 F)
MPPS_FINAL = ("COMPLETED", "DISCONTINUED")


class MppsError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def mpps_create(s: Session, sop_uid: str, *, sps_id: str | None, study_uid: str | None, status: str,
                calling_ae: str) -> Schedule | None:
    """N-CREATE: a modalidade iniciou o exame. Vincula ao agendamento (SPS ID ou Study Instance UID) e o marca
    "em andamento". Exame sem agendamento é aceito (padrão) e só registrado."""
    if status.upper() != "IN PROGRESS":
        raise MppsError(0x0106, "PerformedProcedureStepStatus inicial deve ser IN PROGRESS.")   # invalid attribute value
    if s.execute(select(Schedule).where(Schedule.mpps_uid == sop_uid)).scalar_one_or_none() is not None:
        raise MppsError(0x0111, "MPPS já existente.")                                         # duplicate SOP instance
    q = None
    if sps_id:
        q = select(Schedule).where(Schedule.sps_id == sps_id)
    elif study_uid:
        q = select(Schedule).where(Schedule.study_instance_uid == study_uid)
    sch = s.execute(q).scalar_one_or_none() if q is not None else None
    if sch is not None and sch.mpps_uid is None:
        sch.mpps_uid, sch.mpps_status = sop_uid, "IN PROGRESS"
        old = sch.status
        if sch.status in ("scheduled", "arrived"):
            sch.status = "in_progress"
        s.flush()
        audit.record(s, actor=f"dicom:{calling_ae}", action="ris.mpps.create", target_type="schedule", target_id=sch.id,
                     details={"from": old, "to": sch.status, "calling_ae": calling_ae})
        return sch
    audit.record(s, actor=f"dicom:{calling_ae}", action="ris.mpps.unscheduled", target_type="dicom",
                 details={"calling_ae": calling_ae, "linked": False})
    return None


def performed_from(ds) -> dict[str, list[str]] | None:
    """{Series Instance UID: [SOP Instance UIDs]} da PerformedSeriesSequence (imagens que a modalidade diz ter feito)."""
    seq = getattr(ds, "PerformedSeriesSequence", None) if ds is not None else None
    if not seq:
        return None
    out: dict[str, list[str]] = {}
    for item in seq:
        series = str(getattr(item, "SeriesInstanceUID", "") or "").strip()
        sops = [str(getattr(r, "ReferencedSOPInstanceUID", "") or "").strip()
                for r in (getattr(item, "ReferencedImageSequence", None) or [])]
        if series:
            out.setdefault(series, []).extend(x for x in sops if x)
    return out or None


_DOSE = (("TotalTimeOfFluoroscopy", "fluoro_time_s"), ("TotalNumberOfExposures", "exposures"),
         ("EntranceDoseInmGy", "entrance_dose_mgy"), ("EntranceDose", "entrance_dose_dgy"),
         ("ImageAndFluoroscopyAreaDoseProduct", "dap_dgy_cm2"), ("ExposedArea", "exposed_area_cm2"),
         ("DistanceSourceToEntrance", "source_entrance_mm"), ("CommentsOnRadiationDose", "comments"))
_EXPOSURE = (("KVP", "kvp"), ("XRayTubeCurrentInuA", "tube_current_ua"), ("ExposureTime", "exposure_time_ms"),
             ("RadiationMode", "mode"), ("NumberOfPulses", "pulses"))


def summary_from(ds) -> dict | None:
    """Séries realizadas e módulo Radiation Dose do MPPS, **como informados pela modalidade** (PS3.3 C.4.16 / C.4.17;
    unidades do padrão). Apenas registro: nada é recalculado nem validado."""
    if ds is None:
        return None

    def val(item, kw):
        v = getattr(item, kw, None)
        if v is None or v == "":
            return None
        try:
            return float(v) if not isinstance(v, str) else v.strip()[:200]
        except (TypeError, ValueError):
            return str(v)[:200]
    series = []
    for item in getattr(ds, "PerformedSeriesSequence", None) or []:
        series.append({"series_uid": str(getattr(item, "SeriesInstanceUID", "") or "")[:64],
                       "description": val(item, "SeriesDescription"), "protocol": val(item, "ProtocolName"),
                       "images": len(getattr(item, "ReferencedImageSequence", None) or [])})
    dose = {k: val(ds, kw) for kw, k in _DOSE if val(ds, kw) is not None}
    exposures = [{k: val(e, kw) for kw, k in _EXPOSURE if val(e, kw) is not None}
                 for e in (getattr(ds, "ExposureDoseSequence", None) or [])][:200]
    if exposures:
        dose["exposure_items"] = exposures
    out = {}
    if series:
        out["series"] = series
    if dose:
        out["dose"] = dose
    return out or None


def completeness(s: Session, sch: Schedule) -> dict[str, int] | None:
    """Imagens informadas no MPPS × recebidas pelo PACS (mesma organização). None sem lista do MPPS."""
    if not sch.mpps_performed:
        return None
    from vyonix.pacs.models import PacsInstance
    sops = sorted({u for lst in sch.mpps_performed.values() for u in lst})
    if not sops:
        return None
    got = s.execute(select(func.count()).select_from(PacsInstance).where(PacsInstance.sop_uid.in_(sops))).scalar() or 0
    return {"expected": len(sops), "received": int(got)}


def mpps_set(s: Session, sop_uid: str, *, status: str | None, calling_ae: str,
             performed: dict[str, list[str]] | None = None, summary: dict | None = None) -> Schedule | None:
    """N-SET: andamento/conclusão do exame. COMPLETED conclui o agendamento; DISCONTINUED o devolve à fila
    (o exame não foi feito) e fica na auditoria. Depois de finalizado, o MPPS não muda (PS3.4 F.7.2.2)."""
    sch = s.execute(select(Schedule).where(Schedule.mpps_uid == sop_uid)).scalar_one_or_none()
    if sch is None:
        return None                       # MPPS sem agendamento (aceito no N-CREATE, nada a atualizar)
    if sch.mpps_status in MPPS_FINAL:
        raise MppsError(0x0110, "MPPS já finalizado não pode ser alterado.")                  # processing failure
    st = (status or "").upper()
    if summary:
        sch.mpps_summary = {**(sch.mpps_summary or {}), **summary}
    if not st:
        if performed:
            sch.mpps_performed = performed
        s.flush()
        return sch
    if st not in ("IN PROGRESS",) + MPPS_FINAL:
        raise MppsError(0x0106, "PerformedProcedureStepStatus inválido.")
    old = sch.status
    sch.mpps_status = st
    if performed:
        sch.mpps_performed = performed
    if st == "COMPLETED" and sch.status not in ("cancelled",):
        sch.status = "completed"
    elif st == "DISCONTINUED" and sch.status == "in_progress":
        sch.status = "scheduled"
    s.flush()
    audit.record(s, actor=f"dicom:{calling_ae}", action="ris.mpps.set", target_type="schedule", target_id=sch.id,
                 details={"mpps_status": st, "from": old, "to": sch.status, "calling_ae": calling_ae})
    return sch


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
