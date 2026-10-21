"""Licença: situação por módulo, solicitação (inclusive de demonstração), aplicação de licenças e
autorizações de uso, validação online."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from vyonix.api.app import Ctx, needs
from vyonix.audit import service as audit
from vyonix.tenancy import service as tenancy

router = APIRouter()
MAX_DOC = 200_000


class RequestIn(BaseModel):
    modules: list[str] = Field(min_length=1, max_length=20)
    demo_days: int | None = Field(None, ge=1, le=90)
    contact_name: str = Field(min_length=2, max_length=120)
    contact_email: str = Field(min_length=5, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    contact_phone: str | None = Field(None, max_length=40)
    notes: str | None = Field(None, max_length=500)


class DocIn(BaseModel):
    document: str = Field(min_length=10, max_length=MAX_DOC)


@router.get("/license")
def status(refresh: bool = False, c: Ctx = Depends(needs("core.license.read"))):
    with c.session() as s:
        out = c.plat.licensing.public_status(s, refresh=refresh)
        out["documents"] = c.plat.licensing.documents(s, 20)
        return out


@router.post("/license/request")
def make_request(body: RequestIn, c: Ctx = Depends(needs("core.license.manage"))):
    """Solicitação (ou pedido de demonstração) para enviar ao fornecedor. Não concede nada sozinha."""
    with c.session() as s:
        org = tenancy.organization(s)
        r = c.plat.licensing.request(modules=body.modules, demo_days=body.demo_days, organization=org.name,
                                     contact={"name": body.contact_name, "email": body.contact_email,
                                              "phone": body.contact_phone or "", "notes": body.notes or ""})
        audit.record(s, action="license.request", target_type="license_request", target_id=r["request_id"],
                     details={"modules": sorted(set(body.modules)), "demo_days": body.demo_days}, **c.actor)
    return r


@router.post("/license/install")
def install(body: DocIn, c: Ctx = Depends(needs("core.license.manage"))):
    with c.session() as s:
        return c.plat.licensing.install(s, body.document, **c.actor)


@router.post("/license/authorization")
def authorization(body: DocIn, c: Ctx = Depends(needs("core.license.manage"))):
    with c.session() as s:
        p = c.plat.licensing.apply_authorization(body.document, actor=c.p.username, actor_id=c.p.user_id, ip=c.ip,
                                                 source="file", s=s)
    return {"authorization_id": p["authorization_id"], "seq": p["seq"], "valid_until": p["valid_until"]}


@router.post("/license/check-online")
def check_online(c: Ctx = Depends(needs("core.license.manage"))):
    with c.session() as s:
        return c.plat.licensing.check_online(s, actor=c.p.username)
