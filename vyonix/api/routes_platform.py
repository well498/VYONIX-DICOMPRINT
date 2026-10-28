"""Administração global VYONIX (só a organização operadora): instituições, assistente de cadastro, ativação.
Nenhuma rota daqui devolve dados clínicos."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from vyonix.api.app import Ctx, needs
from vyonix.tenancy import platform_admin as pa

router = APIRouter(prefix="/platform")


def _operator(c: Ctx) -> None:
    with c.session() as s:
        pa.require_operator(s)


class InstitutionIn(BaseModel):
    code: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=2, max_length=200)
    legal_name: str | None = Field(None, max_length=200)
    document: str | None = Field(None, max_length=20)
    institution_type: str
    sites: list[str] = Field(default_factory=list, max_length=50)
    contact_name: str | None = Field(None, max_length=120)
    contact_email: str | None = Field(None, max_length=200)
    contact_phone: str | None = Field(None, max_length=40)
    modules: list[str] = Field(default_factory=list, max_length=10)
    structure: str = "clinica_pequena"
    admin_login: str = Field(min_length=3, max_length=60)
    admin_name: str = Field(min_length=3, max_length=120)
    admin_password: str = Field(min_length=1, max_length=256)


class ActiveIn(BaseModel):
    active: bool
    reason: str | None = Field(None, max_length=300)


@router.get("/institutions")
def institutions(c: Ctx = Depends(needs("platform.institutions.read"))):
    _operator(c)
    return {"items": pa.institutions(c.plat.db), "types": pa.TYPES}


@router.post("/institutions", status_code=201)
def create_institution(body: InstitutionIn, c: Ctx = Depends(needs("platform.institutions.manage"))):
    _operator(c)
    if c.plat.edge:
        from vyonix.errors import ValidationFailed
        raise ValidationFailed("Instituições são cadastradas no servidor VYONIX em nuvem (modo cloud).")
    tid = pa.create_institution(c.plat.db, **body.model_dump(), actor=c.p.username, actor_id=c.p.user_id, ip=c.ip,
                                operator_id=c.p.tenant_id)
    return {"id": str(tid)}


@router.patch("/institutions/{org_id}")
def set_active(org_id: uuid.UUID, body: ActiveIn, c: Ctx = Depends(needs("platform.institutions.manage"))):
    _operator(c)
    pa.set_active(c.plat.db, org_id, body.active, reason=body.reason, actor=c.p.username, actor_id=c.p.user_id,
                  ip=c.ip, operator_id=c.p.tenant_id)
    return {"ok": True}
