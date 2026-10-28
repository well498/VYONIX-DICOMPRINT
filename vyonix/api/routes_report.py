"""REPORT: laudos e modelos (primeira entrega). Redigir e liberar exige o módulo habilitado e licenciado; consultar
laudos existentes não depende de licença vigente (como os estudos do PACS)."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from vyonix.api.app import Ctx, needs
from vyonix.auth import service as auth
from vyonix.errors import Forbidden, NotLicensed
from vyonix.modules import registry
from vyonix.report import physicians as phys
from vyonix.report import service as rep

router = APIRouter(prefix="/report")


def _require(c: Ctx, s) -> None:
    if not registry.is_enabled(s, "report"):
        raise NotLicensed("O módulo VYONIX REPORT não está habilitado nesta organização.", code="module_disabled")
    c.plat.licensing.require_module(s, "report")


class OpenIn(BaseModel):
    study_id: uuid.UUID
    template_id: uuid.UUID | None = None


class DraftIn(BaseModel):
    body: str = Field("", max_length=rep.MAX_BODY)
    critical: bool = False
    critical_note: str | None = Field(None, max_length=300)
    row_version: int | None = None


class SignIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)
    row_version: int | None = None


class AddendumIn(BaseModel):
    text: str = Field(min_length=1, max_length=rep.MAX_BODY)
    critical: bool = False
    password: str = Field(min_length=1, max_length=200)


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    body: str = Field("", max_length=rep.MAX_BODY)
    modality: str | None = Field(None, max_length=16)
    active: bool = True


@router.get("/worklist")
def worklist(status: str | None = None, modality: str | None = None, date_from: date | None = None,
             date_to: date | None = None, patient_id: uuid.UUID | None = None,
             c: Ctx = Depends(needs("report.read"))):
    with c.session() as s:
        return {"items": rep.worklist(s, status=status, modality=modality, date_from=date_from, date_to=date_to,
                                      patient_id=patient_id)}


@router.post("/reports", status_code=201)
def open_report(body: OpenIn, c: Ctx = Depends(needs("report.write"))):
    with c.session() as s:
        _require(c, s)
        r = rep.open_report(s, body.study_id, template_id=body.template_id, **c.actor)
        return rep.get(s, r.id)


@router.get("/reports/{rid}")
def get_report(rid: uuid.UUID, c: Ctx = Depends(needs("report.read"))):
    with c.session() as s:
        return rep.get(s, rid)


@router.put("/reports/{rid}")
def save_draft(rid: uuid.UUID, body: DraftIn, c: Ctx = Depends(needs("report.write"))):
    with c.session() as s:
        _require(c, s)
        rep.update_draft(s, rid, body=body.body, critical=body.critical, critical_note=body.critical_note,
                         expected_version=body.row_version, **c.actor)
        return rep.get(s, rid)


@router.post("/reports/{rid}/finalize")
def finalize(rid: uuid.UUID, body: SignIn, c: Ctx = Depends(needs("report.sign"))):
    with c.session() as s:
        _require(c, s)
    with c.session() as s:                         # tentativa falha fica registrada mesmo sem liberar
        ok = auth.confirm_password(s, c.p, body.password, purpose="report.finalize", ip=c.ip)
    if not ok:
        raise Forbidden("Senha incorreta: o laudo não foi liberado.", code="password_mismatch")
    with c.session() as s:
        rep.finalize(s, rid, expected_version=body.row_version, actor=c.p.display_name or c.p.username,
                     actor_id=c.p.user_id, ip=c.ip)
        return rep.get(s, rid)


@router.post("/reports/{rid}/addenda", status_code=201)
def add_addendum(rid: uuid.UUID, body: AddendumIn, c: Ctx = Depends(needs("report.sign"))):
    with c.session() as s:
        _require(c, s)
    with c.session() as s:
        ok = auth.confirm_password(s, c.p, body.password, purpose="report.addendum", ip=c.ip)
    if not ok:
        raise Forbidden("Senha incorreta: o adendo não foi registrado.", code="password_mismatch")
    with c.session() as s:
        rep.addendum(s, rid, body.text, critical=body.critical, actor=c.p.display_name or c.p.username,
                     actor_id=c.p.user_id, ip=c.ip)
        return rep.get(s, rid)


@router.get("/reports/{rid}/pdf")
def report_pdf(rid: uuid.UUID, c: Ctx = Depends(needs("report.read"))):
    from fastapi.responses import Response
    with c.session() as s:
        data, name = rep.pdf(s, rid, **c.actor)
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.get("/reports/{rid}/verify")
def verify(rid: uuid.UUID, c: Ctx = Depends(needs("report.read"))):
    with c.session() as s:
        return rep.verify(s, rid)


class CommunicateIn(BaseModel):
    notified_to: str = Field(min_length=1, max_length=200)
    channel: str = Field(max_length=40)
    note: str | None = Field(None, max_length=500)


@router.get("/critical")
def critical(status: str | None = "open", c: Ctx = Depends(needs("report.read"))):
    with c.session() as s:
        return {"items": rep.critical_alerts(s, status=status or None)}


@router.post("/critical/{aid}/communicate")
def communicate(aid: uuid.UUID, body: CommunicateIn, c: Ctx = Depends(needs("report.write"))):
    with c.session() as s:
        rep.communicate(s, aid, notified_to=body.notified_to, channel=body.channel, note=body.note, **c.actor)
        return {"items": rep.critical_alerts(s, status="open")}


@router.get("/templates")
def list_templates(modality: str | None = None, include_inactive: bool = False,
                   c: Ctx = Depends(needs("report.read"))):
    with c.session() as s:
        return {"items": rep.templates(s, modality=modality, include_inactive=include_inactive)}


@router.post("/templates", status_code=201)
def create_template(body: TemplateIn, c: Ctx = Depends(needs("report.templates.manage"))):
    with c.session() as s:
        t = rep.save_template(s, name=body.name, body=body.body, modality=body.modality, active=body.active, **c.actor)
        return {"id": str(t.id)}


@router.put("/templates/{tid}")
def update_template(tid: uuid.UUID, body: TemplateIn, c: Ctx = Depends(needs("report.templates.manage"))):
    with c.session() as s:
        t = rep.save_template(s, template_id=tid, name=body.name, body=body.body, modality=body.modality,
                              active=body.active, **c.actor)
        return {"id": str(t.id)}


# ------------------------------------------------------------------ médicos (TELELAUDO T1)
class PhysicianIn(BaseModel):
    user_id: uuid.UUID
    full_name: str = Field(min_length=5, max_length=160)
    crm: str = Field(min_length=1, max_length=20)
    crm_uf: str = Field(min_length=2, max_length=2)
    rqe: str | None = Field(None, max_length=60)
    specialties: list[str] = Field(default_factory=list, max_length=10)
    footer: str | None = Field(None, max_length=200)
    active: bool = True


class LinkIn(BaseModel):
    site_id: uuid.UUID | None = None
    valid_from: date
    valid_to: date | None = None


class EndLinkIn(BaseModel):
    valid_to: date


@router.get("/physicians")
def list_physicians(c: Ctx = Depends(needs("report.physicians.manage"))):
    with c.session() as s:
        return {"items": phys.listing(s)}


@router.get("/physicians/me")
def my_physician(c: Ctx = Depends(needs("report.read"))):
    with c.session() as s:
        return {"physician": phys.of_user(s, c.p.user_id)}


@router.post("/physicians", status_code=201)
def create_physician(body: PhysicianIn, c: Ctx = Depends(needs("report.physicians.manage"))):
    with c.session() as s:
        return {"id": str(phys.save(s, **body.model_dump(), **c.actor).id)}


@router.put("/physicians/{pid}")
def update_physician(pid: uuid.UUID, body: PhysicianIn, c: Ctx = Depends(needs("report.physicians.manage"))):
    with c.session() as s:
        return {"id": str(phys.save(s, physician_id=pid, **body.model_dump(), **c.actor).id)}


@router.post("/physicians/{pid}/links", status_code=201)
def add_link(pid: uuid.UUID, body: LinkIn, c: Ctx = Depends(needs("report.physicians.manage"))):
    with c.session() as s:
        return {"id": str(phys.add_link(s, pid, **body.model_dump(), **c.actor).id)}


@router.post("/physician-links/{lid}/end")
def end_link(lid: uuid.UUID, body: EndLinkIn, c: Ctx = Depends(needs("report.physicians.manage"))):
    with c.session() as s:
        phys.end_link(s, lid, valid_to=body.valid_to, **c.actor)
        return {"ok": True}
