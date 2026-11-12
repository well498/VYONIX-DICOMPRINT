"""Cadastro clínico: pacientes, pedidos, procedimentos, estudos e conciliação."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from vyonix.api.app import Ctx, needs, needs_global
from vyonix.clinical import service as clinical

router = APIRouter()


class IdentifierIn(BaseModel):
    issuer: str = Field(min_length=1, max_length=60)
    value: str = Field(min_length=1, max_length=80)


class PatientIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    birth_date: date | None = None
    sex: str | None = Field(None, pattern="^[MFO]$")
    identifiers: list[IdentifierIn] = Field(default_factory=list, max_length=20)


class PatientPatch(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=200)
    birth_date: date | None = None
    sex: str | None = Field(None, pattern="^[MFO]$")
    row_version: int | None = None


class MergeIn(BaseModel):
    source_id: uuid.UUID
    target_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=500)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ProcedureIn(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=2, max_length=200)
    modality: str | None = Field(None, max_length=8)
    tuss: str | None = Field(None, max_length=12)
    active: bool = True


class OrderIn(BaseModel):
    patient_id: uuid.UUID
    procedure_id: uuid.UUID | None = None
    encounter_id: uuid.UUID | None = None
    requester: str | None = Field(None, max_length=200)
    priority: str = "routine"
    accession: str | None = Field(None, max_length=16)
    site_id: uuid.UUID | None = None                     # P0 0.3.2: unidade do pedido


class StatusIn(BaseModel):
    status: str
    row_version: int | None = None


class ReconcileIn(BaseModel):
    order_id: uuid.UUID


def _patient(s, p, full: bool = False) -> dict:
    out = {"id": str(p.id), "name": p.name, "birth_date": p.birth_date.isoformat() if p.birth_date else None,
           "sex": p.sex, "active": p.active, "merged_into_id": str(p.merged_into_id) if p.merged_into_id else None,
           "row_version": p.row_version,
           "identifiers": [{"issuer": i.issuer, "value": i.value} for i in clinical.identifiers_of(s, p.id)]}
    if full:
        out["merges"] = [{"id": str(m.id), "source_id": str(m.source_id), "target_id": str(m.target_id),
                          "reason": m.reason, "merged_by": m.merged_by, "at": m.created_at.isoformat(),
                          "reverted_at": m.reverted_at.isoformat() if m.reverted_at else None}
                         for m in clinical.merges_of(s, p.id)]
    return out


def _psites(c: Ctx, perm: str, s=None) -> set | None:
    """Unidades do papel; com a sessão, também o vínculo vigente do médico (revisão A04 N3)."""
    from vyonix.auth import scope
    return scope.eff_sites(s, c.p, (perm,)) if s is not None else scope.sites(c.p, (perm,))


def _patient_guard(c: Ctx, s, pid: uuid.UUID, perm: str) -> None:
    """P0 0.3.2: paciente fora das unidades do usuário → 404 (sem revelar existência) + auditoria."""
    from vyonix.auth import scope
    sites = _psites(c, perm, s)
    if not clinical.patient_in_scope(s, pid, sites, allow_unlinked=c.p.has("clinical.patients.write")):
        clinical.get_patient(s, pid)                     # inexistente: 404 normal
        scope.deny(c, "patient", pid, perm, "patient_scope", not_found=True)


def _order_guard(c: Ctx, s, oid: uuid.UUID, perm: str):
    from vyonix.clinical.models import Order
    from vyonix.errors import NotFound
    o = s.get(Order, oid)
    if o is None:
        raise NotFound("Pedido não encontrado.")
    c.require_at(perm, clinical.order_site(s, o), target_type="order", target_id=o.id, not_found=True, s=s)
    return o


def _order(o) -> dict:
    return {"id": str(o.id), "patient_id": str(o.patient_id), "procedure_id": str(o.procedure_id) if o.procedure_id
            else None, "accession": o.accession, "priority": o.priority, "status": o.status,
            "site_id": str(o.site_id) if getattr(o, "site_id", None) else None,
            "requester": o.requester, "created_at": o.created_at.isoformat(), "row_version": o.row_version}


def _study(x) -> dict:
    return {"id": str(x.id), "study_instance_uid": x.study_instance_uid, "accession": x.accession,
            "modality": x.modality, "study_date": x.study_date.isoformat() if x.study_date else None,
            "description": x.description, "patient_id": str(x.patient_id) if x.patient_id else None,
            "order_id": str(x.order_id) if x.order_id else None, "site_id": str(x.site_id) if x.site_id else None,
            "reconciled_at": x.reconciled_at.isoformat() if x.reconciled_at else None}


@router.get("/patients")
def patients(q: str | None = None, identifier: str | None = None, limit: int = 50,
             c: Ctx = Depends(needs("clinical.patients.read"))):
    with c.session() as s:
        return [_patient(s, p) for p in clinical.search_patients(
            s, q=q, identifier=identifier, limit=limit, sites=_psites(c, "clinical.patients.read", s),
            # revisão A04 N6: paciente ainda sem unidade só aparece numa busca dirigida (identificador exato ou
            # nome com 3+ letras), nunca na listagem aberta de quem é restrito a unidades
            allow_unlinked=c.p.has("clinical.patients.write") and bool(
                (identifier or "").strip() or len((q or "").strip()) >= 3))]


@router.post("/patients", status_code=201)
def create_patient(body: PatientIn, c: Ctx = Depends(needs("clinical.patients.write"))):
    with c.session() as s:
        p = clinical.create_patient(s, name=body.name, birth_date=body.birth_date, sex=body.sex,
                                    identifiers=[(i.issuer, i.value) for i in body.identifiers], **c.actor)
        return _patient(s, p)


@router.get("/patients/{pid}")
def get_patient(pid: uuid.UUID, c: Ctx = Depends(needs("clinical.patients.read"))):
    with c.session() as s:
        _patient_guard(c, s, pid, "clinical.patients.read")
        out = _patient(s, clinical.get_patient(s, pid), full=c.p.global_has("clinical.patients.read"))
        return out


@router.patch("/patients/{pid}")
def update_patient(pid: uuid.UUID, body: PatientPatch, c: Ctx = Depends(needs("clinical.patients.write"))):
    data = body.model_dump(exclude_unset=True)
    ver = data.pop("row_version", None)
    with c.session() as s:
        _patient_guard(c, s, pid, "clinical.patients.write")
        return _patient(s, clinical.update_patient(s, pid, expected_version=ver, **data, **c.actor))


@router.post("/patients/{pid}/identifiers")
def add_identifier(pid: uuid.UUID, body: IdentifierIn, c: Ctx = Depends(needs("clinical.patients.write"))):
    with c.session() as s:
        clinical.get_patient(s, pid)
        _patient_guard(c, s, pid, "clinical.patients.write")
        clinical.add_identifier(s, pid, body.issuer, body.value, actor=c.p.username, actor_id=c.p.user_id, ip=c.ip)
        return _patient(s, clinical.get_patient(s, pid))


@router.post("/patients/merge")
def merge(body: MergeIn, c: Ctx = Depends(needs_global("clinical.patients.merge"))):
    with c.session() as s:
        m = clinical.merge_patients(s, source_id=body.source_id, target_id=body.target_id, reason=body.reason,
                                    **c.actor)
        return {"merge_id": str(m.id), "moved": {k: len(v) for k, v in m.moved.items()}}


@router.post("/merges/{merge_id}/undo")
def unmerge(merge_id: uuid.UUID, body: ReasonIn, c: Ctx = Depends(needs_global("clinical.patients.merge"))):
    with c.session() as s:
        clinical.unmerge(s, merge_id, reason=body.reason, **c.actor)
    return {"ok": True}


@router.get("/procedures")
def procedures(c: Ctx = Depends(needs("clinical.orders.read"))):
    with c.session() as s:
        return [{"id": str(p.id), "code": p.code, "name": p.name, "modality": p.modality, "tuss": p.tuss,
                 "active": p.active} for p in clinical.procedures(s, include_inactive=True)]


@router.post("/procedures")
def save_procedure(body: ProcedureIn, c: Ctx = Depends(needs_global("clinical.procedures.manage"))):
    with c.session() as s:
        p = clinical.save_procedure(s, **body.model_dump(), **c.actor)
        return {"id": str(p.id)}


@router.get("/orders")
def orders(patient_id: uuid.UUID | None = None, status: str | None = None, accession: str | None = None,
           c: Ctx = Depends(needs("clinical.orders.read"))):
    with c.session() as s:
        out = [_order(o) for o in clinical.orders(s, patient_id=patient_id, status=status, accession=accession,
                                                  sites=_psites(c, "clinical.orders.read", s))]
        if accession:                                   # busca por número de acesso: mostra o paciente para conferência
            from vyonix.clinical.models import Patient
            for o in out:
                p = s.get(Patient, uuid.UUID(o["patient_id"]))
                o["patient_name"] = p.name if p else None
        return out


@router.post("/orders", status_code=201)
def create_order(body: OrderIn, c: Ctx = Depends(needs("clinical.orders.write"))):
    from vyonix.errors import ValidationFailed
    with c.session() as s:
        data = body.model_dump()
        site = data.get("site_id")
        if data.get("encounter_id"):
            from vyonix.clinical.models import Encounter
            enc = s.get(Encounter, data["encounter_id"])
            site = enc.site_id if enc else site
        mine = _psites(c, "clinical.orders.write", s)
        if site is None and mine is not None:              # P0 0.3.2: usuário restrito sempre informa a unidade
            if len(mine) != 1:
                raise ValidationFailed("Informe a unidade do pedido.", details={"field": "site_id"})
            site = data["site_id"] = next(iter(mine))
        if mine is not None:
            c.require_at("clinical.orders.write", site, target_type="order")
            _patient_guard(c, s, body.patient_id, "clinical.orders.write")
        return _order(clinical.create_order(s, **data, **c.actor))


@router.patch("/orders/{oid}/status")
def order_status(oid: uuid.UUID, body: StatusIn, c: Ctx = Depends(needs("clinical.orders.write"))):
    with c.session() as s:
        _order_guard(c, s, oid, "clinical.orders.write")
        return _order(clinical.set_order_status(s, oid, body.status, expected_version=body.row_version, **c.actor))


@router.get("/studies")
def studies(patient_id: uuid.UUID | None = None, unreconciled: bool = False, unassigned: bool = False,
            c: Ctx = Depends(needs("clinical.studies.read"))):
    from vyonix.errors import Forbidden
    if unassigned and not c.p.global_has("clinical.studies.read"):
        raise Forbidden("A fila de estudos sem unidade é só de quem atua em todas as unidades.", code="global_required")
    with c.session() as s:
        # P0 0.3.2: filtro no SQL antes do limite; estudo sem unidade só para quem tem o papel em todas as unidades
        return [_study(x) for x in clinical.studies(s, patient_id=patient_id, unreconciled=unreconciled,
                                                    unassigned=unassigned, sites=_psites(c, "clinical.studies.read", s))]


@router.post("/studies/{sid}/reconcile")
def reconcile(sid: uuid.UUID, body: ReconcileIn, c: Ctx = Depends(needs("clinical.studies.reconcile"))):
    with c.session() as s:
        from vyonix.clinical.models import Study
        st = s.get(Study, sid)
        if st is not None:                                   # S-02 + P0 0.3.2: unidade do estudo e do pedido
            c.require_at("clinical.studies.reconcile", st.site_id, target_type="study", target_id=st.id, s=s)
            _order_guard(c, s, body.order_id, "clinical.studies.reconcile")
        return _study(clinical.reconcile(s, sid, body.order_id, **c.actor))
