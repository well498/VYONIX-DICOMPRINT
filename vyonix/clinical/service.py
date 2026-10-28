"""Cadastro clínico comum: pacientes, identificadores, atendimentos, procedimentos, pedidos e estudos.

Regras principais:

* Identificador do paciente é único por (clínica, emissor, valor) — o banco garante.
* Mescla de pacientes é **reversível**: tudo que foi movido (identificadores, atendimentos, pedidos,
  estudos) fica registrado em ``clinical.patient_merges``; desfazer devolve exatamente esses itens.
  O cadastro de origem não é apagado (fica inativo, apontando para o destino).
* Conciliação de estudos: por número de acesso (``accession``) quando o estudo chega ou quando o
  pedido é criado (consumidor de eventos), ou manualmente.
* Eventos levam apenas identificadores internos — nunca nome, documento ou dados clínicos.
"""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import date, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from vyonix.audit import service as audit
from vyonix.clinical.models import (Encounter, Order, Patient, PatientIdentifier, PatientMerge, Procedure, Study)
from vyonix.db.base import utcnow
from vyonix.errors import Conflict, NotFound, ValidationFailed
from vyonix.events.bus import Bus, Event, publish
from vyonix.settings import service as settings

SEXES = ("M", "F", "O")
PRIORITIES = ("routine", "urgent", "stat")
ORDER_STATUSES = ("requested", "scheduled", "arrived", "in_progress", "completed", "cancelled")
UID_RE = re.compile(r"^[0-9]+(\.[0-9]+)*$")


def _clean_name(name: str) -> str:
    n = " ".join((name or "").split())
    if not 2 <= len(n) <= 200:
        raise ValidationFailed("Nome do paciente: de 2 a 200 caracteres.")
    return n


def _check_version(obj, expected: int | None) -> None:
    if expected is not None and obj.row_version != expected:
        raise Conflict("O registro foi alterado por outra pessoa. Recarregue e tente de novo.")


# --------------------------------------------------------------------------- pacientes

def create_patient(s: Session, *, name: str, birth_date: date | None = None, sex: str | None = None,
                   identifiers: list[tuple[str, str]] | None = None, actor: str, actor_id=None, ip=None) -> Patient:
    if sex and sex not in SEXES:
        raise ValidationFailed("Sexo: M, F ou O.")
    if birth_date and birth_date > date.today():
        raise ValidationFailed("Data de nascimento no futuro.")
    pol = settings.get(s, "clinical", "policy")
    ids = [(i.strip(), v.strip()) for i, v in (identifiers or []) if i and v and i.strip() and v.strip()]
    if pol["require_identifier_issuer"] and not any(i == pol["require_identifier_issuer"] for i, _ in ids):
        raise ValidationFailed(f"Informe o identificador obrigatório ({pol['require_identifier_issuer']}).")
    p = Patient(name=_clean_name(name), birth_date=birth_date, sex=sex)
    s.add(p)
    s.flush()
    for issuer, value in ids:
        add_identifier(s, p.id, issuer, value, actor=actor, audit_it=False)
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="patient.create", target_type="patient",
                 target_id=p.id, details={"identifiers": [i for i, _ in ids]})
    publish(s, "clinical.patient.created.v1", {"patient_id": str(p.id)}, source="clinical", subject_kind="patient",
            subject_id=p.id)
    return p


def add_identifier(s: Session, patient_id: uuid.UUID, issuer: str, value: str, *, actor: str, audit_it: bool = True,
                   actor_id=None, ip=None) -> PatientIdentifier:
    issuer, value = issuer.strip()[:60], value.strip()[:80]
    if not issuer or not value:
        raise ValidationFailed("Emissor e valor do identificador são obrigatórios.")
    dup = s.execute(select(PatientIdentifier).where(PatientIdentifier.issuer == issuer,
                                                    PatientIdentifier.value == value)).scalar_one_or_none()
    if dup:
        if dup.patient_id == patient_id:
            return dup
        raise Conflict(f"O identificador {issuer} {value} já pertence a outro paciente.",
                       details={"patient_id": str(dup.patient_id)})
    pi = PatientIdentifier(patient_id=patient_id, issuer=issuer, value=value)
    s.add(pi)
    s.flush()
    if audit_it:
        audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="patient.identifier_add", target_type="patient",
                     target_id=patient_id, details={"issuer": issuer})
    return pi


def get_patient(s: Session, patient_id: uuid.UUID) -> Patient:
    p = s.get(Patient, patient_id)
    if p is None:
        raise NotFound("Paciente não encontrado.")
    return p


def update_patient(s: Session, patient_id: uuid.UUID, *, actor: str, expected_version: int | None = None,
                   actor_id=None, ip=None, **fields) -> Patient:
    p = get_patient(s, patient_id)
    if p.merged_into_id:
        raise Conflict("Cadastro mesclado em outro paciente: altere o cadastro de destino.")
    _check_version(p, expected_version)
    changed = []
    if fields.get("name") is not None:
        n = _clean_name(fields["name"])
        if n != p.name:
            p.name = n
            changed.append("name")
    if "birth_date" in fields and fields["birth_date"] != p.birth_date:
        if fields["birth_date"] and fields["birth_date"] > date.today():
            raise ValidationFailed("Data de nascimento no futuro.")
        p.birth_date = fields["birth_date"]
        changed.append("birth_date")
    if "sex" in fields and fields["sex"] != p.sex:
        if fields["sex"] and fields["sex"] not in SEXES:
            raise ValidationFailed("Sexo: M, F ou O.")
        p.sex = fields["sex"]
        changed.append("sex")
    if changed:
        s.flush()
        audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="patient.update", target_type="patient",
                     target_id=p.id, details={"fields": changed})
        publish(s, "clinical.patient.updated.v1", {"patient_id": str(p.id), "fields": changed}, source="clinical",
                subject_kind="patient", subject_id=p.id)
    return p


def search_patients(s: Session, *, q: str | None = None, identifier: str | None = None, include_merged: bool = False,
                    limit: int = 50) -> list[Patient]:
    stmt = select(Patient).order_by(Patient.name).limit(min(limit, 200))
    if not include_merged:
        stmt = stmt.where(Patient.merged_into_id.is_(None))
    if identifier:
        stmt = stmt.where(Patient.id.in_(select(PatientIdentifier.patient_id)
                                         .where(PatientIdentifier.value == identifier.strip())))
    if q:
        terms = [t for t in q.split() if t]
        for t in terms[:5]:
            stmt = stmt.where(Patient.name.ilike(f"%{t.replace('%', '').replace('_', '')}%"))
    return list(s.execute(stmt).scalars())


def identifiers_of(s: Session, patient_id: uuid.UUID) -> list[PatientIdentifier]:
    return list(s.execute(select(PatientIdentifier).where(PatientIdentifier.patient_id == patient_id)
                          .order_by(PatientIdentifier.issuer)).scalars())


# --------------------------------------------------------------------------- mescla reversível

_MOVABLE = (("identifiers", PatientIdentifier), ("encounters", Encounter), ("orders", Order), ("studies", Study))


def merge_patients(s: Session, *, source_id: uuid.UUID, target_id: uuid.UUID, reason: str, actor: str,
                   actor_id=None, ip=None) -> PatientMerge:
    if source_id == target_id:
        raise ValidationFailed("Escolha dois cadastros diferentes.")
    if not (reason or "").strip():
        raise ValidationFailed("Informe o motivo da mescla.")
    src, dst = get_patient(s, source_id), get_patient(s, target_id)
    if src.merged_into_id or dst.merged_into_id:
        raise Conflict("Um dos cadastros já foi mesclado.")
    moved: dict[str, list[str]] = {}
    for key, model in _MOVABLE:
        rows = list(s.execute(select(model).where(model.patient_id == src.id).with_for_update()).scalars())
        for r in rows:
            r.patient_id = dst.id
        moved[key] = [str(r.id) for r in rows]
    src.merged_into_id, src.active = dst.id, False
    m = PatientMerge(source_id=src.id, target_id=dst.id, moved=moved, reason=reason.strip(), merged_by=actor)
    s.add(m)
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="patient.merge", target_type="patient",
                 target_id=dst.id, details={"source_id": str(src.id), "merge_id": str(m.id),
                                            "moved": {k: len(v) for k, v in moved.items()}, "reason": reason})
    publish(s, "clinical.patient.merged.v1", {"merge_id": str(m.id), "source_id": str(src.id),
                                              "target_id": str(dst.id)}, source="clinical", subject_kind="patient",
            subject_id=dst.id)
    return m


def unmerge(s: Session, merge_id: uuid.UUID, *, actor: str, reason: str, actor_id=None, ip=None) -> PatientMerge:
    m = s.get(PatientMerge, merge_id)
    if m is None:
        raise NotFound("Mescla não encontrada.")
    if m.reverted_at:
        raise Conflict("Esta mescla já foi desfeita.")
    src = get_patient(s, m.source_id)
    later = s.execute(select(PatientMerge).where(PatientMerge.source_id == m.target_id,
                                                 PatientMerge.reverted_at.is_(None))).scalar_one_or_none()
    if later:
        raise Conflict("O cadastro de destino foi mesclado depois em outro; desfaça aquela mescla primeiro.")
    returned: dict[str, int] = {}
    for key, model in _MOVABLE:
        ids = [uuid.UUID(x) for x in (m.moved or {}).get(key, [])]
        n = 0
        if ids:
            for r in s.execute(select(model).where(model.id.in_(ids), model.patient_id == m.target_id)
                               .with_for_update()).scalars():
                r.patient_id = src.id
                n += 1
        returned[key] = n
    src.merged_into_id, src.active = None, True
    m.reverted_at, m.reverted_by = utcnow(), actor
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="patient.unmerge", target_type="patient",
                 target_id=src.id, details={"merge_id": str(m.id), "returned": returned, "reason": reason})
    publish(s, "clinical.patient.unmerged.v1", {"merge_id": str(m.id), "source_id": str(src.id),
                                                "target_id": str(m.target_id)}, source="clinical",
            subject_kind="patient", subject_id=src.id)
    return m


def merges_of(s: Session, patient_id: uuid.UUID) -> list[PatientMerge]:
    return list(s.execute(select(PatientMerge).where(or_(PatientMerge.source_id == patient_id,
                                                         PatientMerge.target_id == patient_id))
                          .order_by(PatientMerge.created_at.desc())).scalars())


# --------------------------------------------------------------------------- atendimentos, procedimentos, pedidos

def create_encounter(s: Session, *, patient_id: uuid.UUID, site_id: uuid.UUID, number: str | None = None,
                     actor: str, actor_id=None, ip=None) -> Encounter:
    p = get_patient(s, patient_id)
    if p.merged_into_id:
        raise Conflict("Cadastro mesclado: use o cadastro de destino.")
    number = (number or f"{utcnow():%Y%m%d}-{secrets.token_hex(3).upper()}").strip()[:40]
    if s.execute(select(Encounter).where(Encounter.site_id == site_id, Encounter.number == number)).first():
        raise Conflict("Já existe um atendimento com esse número nesta unidade.")
    e = Encounter(patient_id=p.id, site_id=site_id, number=number, arrived_at=utcnow(), status="open")
    s.add(e)
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="encounter.create", target_type="encounter",
                 target_id=e.id, details={"site_id": str(site_id)})
    return e


def save_procedure(s: Session, *, code: str, name: str, modality: str | None = None, tuss: str | None = None,
                   active: bool = True, actor: str, actor_id=None, ip=None) -> Procedure:
    code = code.strip().upper()
    if not re.fullmatch(r"[A-Z0-9._-]{1,30}", code):
        raise ValidationFailed("Código do procedimento: letras, números, ponto, hífen (até 30).")
    if modality and not re.fullmatch(r"[A-Z]{2,8}", modality):
        raise ValidationFailed("Modalidade DICOM inválida (ex.: CT, MR, CR, DX, US).")
    pr = s.execute(select(Procedure).where(Procedure.code == code)).scalar_one_or_none()
    if pr is None:
        pr = Procedure(code=code, name=name.strip(), modality=modality, tuss=tuss, active=active)
        s.add(pr)
    else:
        pr.name, pr.modality, pr.tuss, pr.active = name.strip(), modality, tuss, active
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="procedure.save", target_type="procedure",
                 target_id=pr.id, details={"code": code})
    return pr


def procedures(s: Session, include_inactive: bool = False) -> list[Procedure]:
    q = select(Procedure).order_by(Procedure.name)
    if not include_inactive:
        q = q.where(Procedure.active.is_(True))
    return list(s.execute(q).scalars())


def _new_accession(s: Session) -> str:
    prefix = settings.get(s, "clinical", "policy")["accession_prefix"]
    for _ in range(20):
        acc = f"{prefix}{utcnow():%y%m%d}{secrets.randbelow(10 ** 6):06d}"[:16]
        if not s.execute(select(Order.id).where(Order.accession == acc)).first():
            return acc
    raise Conflict("Não foi possível gerar o número de acesso; tente de novo.")


def create_order(s: Session, *, patient_id: uuid.UUID, procedure_id: uuid.UUID | None = None,
                 encounter_id: uuid.UUID | None = None, requester: str | None = None, priority: str = "routine",
                 accession: str | None = None, actor: str, actor_id=None, ip=None) -> Order:
    p = get_patient(s, patient_id)
    if p.merged_into_id:
        raise Conflict("Cadastro mesclado: use o cadastro de destino.")
    if priority not in PRIORITIES:
        raise ValidationFailed("Prioridade: routine, urgent ou stat.")
    if procedure_id and not s.get(Procedure, procedure_id):
        raise NotFound("Procedimento não encontrado.")
    if encounter_id:
        enc = s.get(Encounter, encounter_id)
        if not enc or enc.patient_id != p.id:
            raise ValidationFailed("Atendimento não pertence a este paciente.")
    if accession:
        accession = accession.strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,16}", accession):     # AccessionNumber DICOM: SH, até 16
            raise ValidationFailed("Número de acesso inválido (até 16 caracteres).")
        if s.execute(select(Order.id).where(Order.accession == accession)).first():
            raise Conflict("Número de acesso já utilizado.")
    o = Order(patient_id=p.id, procedure_id=procedure_id, encounter_id=encounter_id, requester=requester,
              priority=priority, accession=accession or _new_accession(s), status="requested")
    s.add(o)
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="order.create", target_type="order",
                 target_id=o.id, details={"accession": o.accession, "priority": priority})
    publish(s, "clinical.order.created.v1", {"order_id": str(o.id), "accession": o.accession}, source="clinical",
            subject_kind="order", subject_id=o.id)
    return o


def set_order_status(s: Session, order_id: uuid.UUID, status: str, *, actor: str, expected_version: int | None = None,
                     actor_id=None, ip=None) -> Order:
    if status not in ORDER_STATUSES:
        raise ValidationFailed("Situação inválida.")
    o = s.get(Order, order_id)
    if o is None:
        raise NotFound("Pedido não encontrado.")
    _check_version(o, expected_version)
    if o.status in ("completed", "cancelled") and status != o.status:
        raise Conflict("Pedido concluído ou cancelado não muda de situação.")
    old, o.status = o.status, status
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="order.status", target_type="order",
                 target_id=o.id, details={"from": old, "to": status})
    publish(s, "clinical.order.updated.v1", {"order_id": str(o.id), "status": status}, source="clinical",
            subject_kind="order", subject_id=o.id)
    return o


def orders(s: Session, *, patient_id: uuid.UUID | None = None, status: str | None = None,
           accession: str | None = None, limit: int = 100) -> list[Order]:
    q = select(Order).order_by(Order.created_at.desc()).limit(min(limit, 500))
    if accession:
        q = q.where(Order.accession == accession.strip())
    if patient_id:
        q = q.where(Order.patient_id == patient_id)
    if status:
        q = q.where(Order.status == status)
    return list(s.execute(q).scalars())


# --------------------------------------------------------------------------- estudos e conciliação

def register_study(s: Session, *, study_instance_uid: str, accession: str | None = None, modality: str | None = None,
                   study_date: date | None = None, description: str | None = None, site_id: uuid.UUID | None = None,
                   patient_identifier: tuple[str, str] | None = None, storage_location: str | None = None,
                   actor: str) -> Study:
    """Registra (ou atualiza) um estudo recebido. A conciliação com o pedido acontece pelo consumidor
    de eventos — ou manualmente, se não houver número de acesso correspondente."""
    uid = study_instance_uid.strip()
    if not UID_RE.match(uid) or len(uid) > 64:
        raise ValidationFailed("Study Instance UID inválido.")
    st = s.execute(select(Study).where(Study.study_instance_uid == uid)).scalar_one_or_none()
    created = st is None
    if created:
        st = Study(study_instance_uid=uid)
        s.add(st)
    st.accession = (accession or "").strip()[:32] or st.accession
    st.modality, st.study_date = modality or st.modality, study_date or st.study_date
    st.description = (description or st.description or "")[:200] or None
    st.site_id, st.storage_location = site_id or st.site_id, storage_location or st.storage_location
    if st.patient_id is None and patient_identifier:
        pi = s.execute(select(PatientIdentifier).where(PatientIdentifier.issuer == patient_identifier[0],
                                                       PatientIdentifier.value == patient_identifier[1])
                       ).scalar_one_or_none()
        if pi:
            st.patient_id = pi.patient_id
    s.flush()
    if created:
        audit.record(s, actor=actor, action="study.register", target_type="study", target_id=st.id,
                     details={"modality": st.modality})
        publish(s, "clinical.study.registered.v1", {"study_id": str(st.id), "accession": st.accession},
                source="clinical", subject_kind="study", subject_id=st.id)
    return st


def reconcile(s: Session, study_id: uuid.UUID, order_id: uuid.UUID, *, actor: str, how: str = "manual",
              actor_id=None, ip=None) -> Study:
    st, o = s.get(Study, study_id), s.get(Order, order_id)
    if st is None or o is None:
        raise NotFound("Estudo ou pedido não encontrado.")
    if st.order_id and st.order_id != o.id:
        raise Conflict("Estudo já conciliado com outro pedido.")
    if st.patient_id and st.patient_id != o.patient_id:
        raise Conflict("O estudo pertence a outro paciente. Corrija o cadastro (ou mescle) antes de conciliar.")
    st.order_id, st.patient_id, st.reconciled_at = o.id, o.patient_id, utcnow()
    if not st.accession:
        st.accession = o.accession
    if o.status in ("requested", "scheduled", "arrived"):
        o.status = "in_progress"
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="study.reconcile", target_type="study",
                 target_id=st.id, details={"order_id": str(o.id), "how": how})
    publish(s, "clinical.study.reconciled.v1", {"study_id": str(st.id), "order_id": str(o.id), "how": how},
            source="clinical", subject_kind="study", subject_id=st.id)
    return st


def studies(s: Session, *, patient_id: uuid.UUID | None = None, unreconciled: bool = False,
            limit: int = 100) -> list[Study]:
    q = select(Study).order_by(Study.created_at.desc()).limit(min(limit, 500))
    if patient_id:
        q = q.where(Study.patient_id == patient_id)
    if unreconciled:
        q = q.where(Study.order_id.is_(None))
    return list(s.execute(q).scalars())


def register_consumers(bus: Bus) -> None:
    """Conciliação automática por número de acesso (estudo chegou ou pedido criado)."""

    def auto(s: Session, ev: Event) -> None:
        if not settings.get(s, "clinical", "policy")["auto_reconcile_by_accession"]:
            return
        acc = ev.data.get("accession")
        if not acc:
            return
        o = s.execute(select(Order).where(Order.tenant_id == ev.tenant_id, Order.accession == acc)).scalar_one_or_none()
        if o is None or o.status == "cancelled":
            return
        for st in s.execute(select(Study).where(Study.tenant_id == ev.tenant_id, Study.accession == acc,
                                                Study.order_id.is_(None))).scalars():
            if st.patient_id and st.patient_id != o.patient_id:
                audit.record(s, actor="conciliação", action="study.reconcile_conflict", target_type="study",
                             target_id=st.id, details={"order_id": str(o.id)}, tenant_id=ev.tenant_id)
                continue
            reconcile(s, st.id, o.id, actor="conciliação", how="accession")

    bus.subscribe("clinical.study.registered.v1", "clinical.reconcile.study")(auto)
    bus.subscribe("clinical.order.created.v1", "clinical.reconcile.order")(auto)
