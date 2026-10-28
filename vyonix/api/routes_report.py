"""REPORT: laudos e modelos (primeira entrega). Redigir e liberar exige o módulo habilitado e licenciado; consultar
laudos existentes não depende de licença vigente (como os estudos do PACS)."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from vyonix.api.app import Ctx, needs
from vyonix.auth import service as auth
from vyonix.errors import Forbidden, NotLicensed
from vyonix.modules import registry
from vyonix.report import branding as brand
from vyonix.report import physicians as phys
from vyonix.report import service as rep
from vyonix.report import templates as tpl

router = APIRouter(prefix="/report")


def _require(c: Ctx, s) -> None:
    if not registry.is_enabled(s, "report"):
        raise NotLicensed("O módulo VYONIX REPORT não está habilitado nesta organização.", code="module_disabled")
    c.plat.licensing.require_module(s, "report")


class OpenIn(BaseModel):
    study_id: uuid.UUID
    template_id: uuid.UUID | None = None
    auto: bool = False


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
    body: str = Field("", max_length=rep.MAX_BODY)            # compatibilidade: vira a seção de achados
    technique: str = Field("", max_length=10000)
    findings: str | None = Field(None, max_length=10000)
    conclusion: str = Field("", max_length=10000)
    modality: str | None = Field(None, max_length=16)
    procedure_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    preferred: bool = False
    active: bool = True

    def kw(self) -> dict:
        return {"name": self.name, "modality": self.modality, "active": self.active, "technique": self.technique,
                "findings": self.findings if self.findings is not None else self.body, "conclusion": self.conclusion,
                "procedure_id": self.procedure_id, "site_id": self.site_id, "preferred": self.preferred}


class PublishIn(BaseModel):
    reviewed: bool = False


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
        r = rep.open_report(s, body.study_id, template_id=body.template_id, auto=body.auto, **c.actor)
        return rep.get(s, r.id)


@router.get("/suggest")
def suggest(study_id: uuid.UUID, c: Ctx = Depends(needs("report.write"))):
    """Modelo que a seleção automática usaria para o exame (e por qual regra)."""
    with c.session() as s:
        return tpl.select_for(s, study_id)


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
def list_templates(modality: str | None = None, include_inactive: bool = False, published: bool = False,
                   c: Ctx = Depends(needs("report.read"))):
    with c.session() as s:
        return {"items": rep.templates(s, modality=modality, include_inactive=include_inactive,
                                       only_published=published),
                "fields": tpl.FIELDS}


@router.post("/templates", status_code=201)
def create_template(body: TemplateIn, c: Ctx = Depends(needs("report.templates.manage"))):
    with c.session() as s:
        t, v = tpl.save(s, **body.kw(), **c.actor)
        return {"id": str(t.id), "version": v.version, "status": v.status}


@router.put("/templates/{tid}")
def update_template(tid: uuid.UUID, body: TemplateIn, c: Ctx = Depends(needs("report.templates.manage"))):
    with c.session() as s:
        t, v = tpl.save(s, template_id=tid, **body.kw(), **c.actor)
        return {"id": str(t.id), "version": v.version, "status": v.status}


@router.post("/templates/{tid}/publish")
def publish_template(tid: uuid.UUID, body: PublishIn, c: Ctx = Depends(needs("report.templates.manage"))):
    with c.session() as s:
        v = tpl.publish(s, tid, reviewed=body.reviewed, **c.actor)
        return {"id": str(tid), "version": v.version, "status": v.status}


@router.get("/templates/{tid}/preview")
def preview_template(tid: uuid.UUID, c: Ctx = Depends(needs("report.templates.manage"))):
    """PDF A4 do rascunho (ou da versão publicada) com dados fictícios e a identidade da organização."""
    from fastapi.responses import Response
    from vyonix.errors import NotFound
    from vyonix.report import pdf
    from vyonix.report.models import ReportTemplate
    from vyonix.settings import service as settings
    with c.session() as s:
        t = s.get(ReportTemplate, tid)
        if t is None:
            raise NotFound("Modelo não encontrado.")
        item = next(x for x in tpl.listing(s, include_inactive=True) if x["id"] == str(tid))
        text = tpl.compose(item["draft"], tpl.sample_context()) if item["draft"] else \
            tpl.render(item["body"], tpl.sample_context())
        data = pdf.preview(brand.effective(s, None), settings.get(s, "core", "institution"), body=text)
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="previa-modelo.pdf"', "Cache-Control": "no-store"})


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


# ------------------------------------------------------------------ identidade visual (TELELAUDO T2)
class BrandingIn(BaseModel):
    site_id: uuid.UUID | None = None
    settings: dict = Field(default_factory=dict)
    logo_asset_id: uuid.UUID | None = None
    letterhead_asset_id: uuid.UUID | None = None
    keep_images: bool = True


@router.get("/branding")
def get_branding(c: Ctx = Depends(needs("report.branding.manage"))):
    with c.session() as s:
        return brand.describe(s)


@router.post("/branding/assets", status_code=201)
async def upload_asset(request: Request, kind: str, c: Ctx = Depends(needs("report.branding.manage"))):
    from vyonix.errors import ValidationFailed
    data = bytearray()
    async for chunk in request.stream():                  # leitura limitada (não carrega envio gigante na memória)
        data += chunk
        if len(data) > brand.MAX_BYTES:
            raise ValidationFailed("Imagem acima de 2 MB.")
    data = bytes(data)
    with c.session() as s:
        a = brand.store_asset(s, kind, data, **c.actor)
        return {"id": str(a.id), "sha256": a.sha256, "width": a.width, "height": a.height, "media_type": a.media_type}


@router.post("/branding", status_code=201)
def save_branding(body: BrandingIn, c: Ctx = Depends(needs("report.branding.manage"))):
    with c.session() as s:
        v = brand.save(s, **body.model_dump(), **c.actor)
        return {"id": str(v.id), "version": v.version}


@router.get("/branding/preview")
def preview_branding(site_id: uuid.UUID | None = None, c: Ctx = Depends(needs("report.branding.manage"))):
    from fastapi.responses import Response
    from vyonix.report import pdf
    from vyonix.settings import service as settings
    with c.session() as s:
        data = pdf.preview(brand.effective(s, site_id), settings.get(s, "core", "institution"), pages=2)
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="previa-identidade.pdf"', "Cache-Control": "no-store"})
