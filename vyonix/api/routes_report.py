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
from vyonix.report import signature as sig
from vyonix.report import service as rep
from vyonix.report import templates as tpl

router = APIRouter(prefix="/report")


def _require(c: Ctx, s) -> None:
    if not registry.is_enabled(s, "report"):
        raise NotLicensed("O módulo VYONIX REPORT não está habilitado nesta organização.", code="module_disabled")
    c.plat.licensing.require_module(s, "report")


def _scope(c: Ctx, s):
    from vyonix.report import queue
    return queue.scope(s, c.p.user_id, can_assign=c.p.has("report.assign"))


def _in_scope(c: Ctx, s, *, study_id: uuid.UUID | None = None, report_id: uuid.UUID | None = None) -> None:
    """Médico só acessa exame/laudo de unidade com vínculo vigente (TELELAUDO T7)."""
    from vyonix.errors import NotFound
    from vyonix.report import queue
    from vyonix.report.models import Report
    if report_id is not None:
        r = s.get(Report, report_id)
        if r is None:
            raise NotFound("Laudo não encontrado.")
        study_id = r.study_id
    from vyonix.ris import prep
    if study_id in prep.shared_studies(s, c.p.user_id):     # compartilhado temporariamente com este usuário
        return
    queue.require(s, _scope(c, s), study_id)


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
    signature_block: dict | None = None

    def kw(self) -> dict:
        return {"name": self.name, "modality": self.modality, "active": self.active, "technique": self.technique,
                "findings": self.findings if self.findings is not None else self.body, "conclusion": self.conclusion,
                "procedure_id": self.procedure_id, "site_id": self.site_id, "preferred": self.preferred,
                "signature_block": self.signature_block}


class PublishIn(BaseModel):
    reviewed: bool = False


@router.get("/worklist")
def worklist(status: str | None = None, modality: str | None = None, date_from: date | None = None,
             date_to: date | None = None, patient_id: uuid.UUID | None = None, mine: bool = False,
             c: Ctx = Depends(needs("report.read"))):
    from vyonix.report import distribution
    from vyonix.ris import prep
    from vyonix.settings import service as settings
    with c.session() as s:
        distribution.release_expired(s)                       # reservas abandonadas voltam à fila
        req = settings.get(s, "ris", "preparation")["require_forward"]
        return {"items": rep.worklist(s, status=status, modality=modality, date_from=date_from, date_to=date_to,
                                      patient_id=patient_id, scope=_scope(c, s),
                                      mine=c.p.user_id if mine else None, shared=prep.shared_studies(s, c.p.user_id),
                                      require_forward=req)}


@router.post("/queue/{study_id}/claim")
def claim(study_id: uuid.UUID, c: Ctx = Depends(needs("report.write"))):
    """O médico reserva um exame livre (expira se o laudo não for iniciado)."""
    from vyonix.report import distribution
    with c.session() as s:
        _in_scope(c, s, study_id=study_id)
        a = distribution.claim(s, study_id, c.p.user_id, actor=c.p.username, ip=c.ip)
        return {"assignment_id": str(a.id), "reserved_until": a.reserved_until.isoformat() if a.reserved_until else None}


@router.delete("/queue/{study_id}/claim")
def release_claim(study_id: uuid.UUID, c: Ctx = Depends(needs("report.write"))):
    from vyonix.report import distribution
    with c.session() as s:
        distribution.release(s, study_id, c.p.user_id, actor=c.p.username, ip=c.ip)
    return {"ok": True}


@router.post("/reports", status_code=201)
def open_report(body: OpenIn, c: Ctx = Depends(needs("report.write"))):
    with c.session() as s:
        _require(c, s)
        _in_scope(c, s, study_id=body.study_id)
        r = rep.open_report(s, body.study_id, template_id=body.template_id, auto=body.auto, **c.actor)
        return rep.get(s, r.id)


@router.get("/suggest")
def suggest(study_id: uuid.UUID, c: Ctx = Depends(needs("report.write"))):
    """Modelo que a seleção automática usaria para o exame (e por qual regra)."""
    with c.session() as s:
        _in_scope(c, s, study_id=study_id)
        return tpl.select_for(s, study_id)


@router.get("/reports/{rid}")
def get_report(rid: uuid.UUID, c: Ctx = Depends(needs("report.read"))):
    with c.session() as s:
        _in_scope(c, s, report_id=rid)
        return rep.get(s, rid)


@router.put("/reports/{rid}")
def save_draft(rid: uuid.UUID, body: DraftIn, c: Ctx = Depends(needs("report.write"))):
    with c.session() as s:
        _require(c, s)
        _in_scope(c, s, report_id=rid)
        rep.update_draft(s, rid, body=body.body, critical=body.critical, critical_note=body.critical_note,
                         expected_version=body.row_version, **c.actor)
        return rep.get(s, rid)


@router.post("/reports/{rid}/finalize")
def finalize(rid: uuid.UUID, body: SignIn, c: Ctx = Depends(needs("report.sign"))):
    with c.session() as s:
        _require(c, s)
        _in_scope(c, s, report_id=rid)
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
        _in_scope(c, s, report_id=rid)
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
        _in_scope(c, s, report_id=rid)
        data, name = rep.pdf(s, rid, signature_key=_sig_key(c), **c.actor)
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.get("/reports/{rid}/draft-pdf")
def report_draft_pdf(rid: uuid.UUID, c: Ctx = Depends(needs("report.read"))):
    """Prévia do rascunho: marcada "RASCUNHO — NÃO FINALIZADO", sem assinatura nem imagem."""
    from fastapi.responses import Response
    with c.session() as s:
        _in_scope(c, s, report_id=rid)
        data, name = rep.pdf(s, rid, draft=True, **c.actor)
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}"', "Cache-Control": "no-store"})


class BatchIn(BaseModel):
    report_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=200)
    confirm: bool = False


@router.post("/reports/finalize-batch")
def finalize_batch(body: BatchIn, c: Ctx = Depends(needs("report.sign"))):
    """Liberação de vários laudos do próprio médico: autorização explícita (``confirm``) e senha uma vez; cada laudo
    é liberado e auditado individualmente (com o identificador do lote); uma falha não afeta os demais."""
    from vyonix.errors import ValidationFailed, VyonixError
    if not body.confirm:
        raise ValidationFailed("Confirme explicitamente a liberação de todos os laudos selecionados.")
    ids = list(dict.fromkeys(body.report_ids))
    with c.session() as s:
        _require(c, s)
    with c.session() as s:
        ok = auth.confirm_password(s, c.p, body.password, purpose="report.finalize_batch", ip=c.ip)
    if not ok:
        raise Forbidden("Senha incorreta: nenhum laudo foi liberado.", code="password_mismatch")
    batch = str(uuid.uuid4())
    results = []
    for rid in ids:
        try:
            with c.session() as s:
                _in_scope(c, s, report_id=rid)
                r = rep.finalize(s, rid, actor=c.p.display_name or c.p.username, actor_id=c.p.user_id, ip=c.ip,
                                 batch=batch)
                results.append({"report_id": str(rid), "ok": True, "version": r.version})
        except VyonixError as exc:
            results.append({"report_id": str(rid), "ok": False, "code": exc.code, "message": str(exc)})
    return {"batch": batch, "released": sum(1 for x in results if x["ok"]), "results": results}


@router.get("/reports/{rid}/verify")
def verify(rid: uuid.UUID, c: Ctx = Depends(needs("report.read"))):
    with c.session() as s:
        _in_scope(c, s, report_id=rid)
        return rep.verify(s, rid)


class CommunicateIn(BaseModel):
    notified_to: str = Field(min_length=1, max_length=200)
    channel: str = Field(max_length=40)
    note: str | None = Field(None, max_length=500)


@router.get("/critical")
def critical(status: str | None = "open", c: Ctx = Depends(needs("report.read"))):
    from vyonix.report import queue
    with c.session() as s:
        sc = _scope(c, s)
        return {"items": [x for x in rep.critical_alerts(s, status=status or None)
                          if queue.allowed(sc, uuid.UUID(x["site_id"]) if x["site_id"] else None)]}


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


@router.post("/templates/import-docx", status_code=201)
async def import_docx(request: Request, name: str | None = None, modality: str | None = None,
                      c: Ctx = Depends(needs("report.templates.manage"))):
    """Importação assistida: cria um **rascunho** com o relatório de incompatibilidades (publicar exige conferência)."""
    from vyonix.errors import ValidationFailed
    from vyonix.report import docx_import
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > docx_import.MAX_BYTES:
            raise ValidationFailed("Arquivo acima de 5 MB.")
    conv = docx_import.convert(bytes(data))
    bad = tpl.unknown_fields(conv["technique"], conv["findings"], conv["conclusion"])
    for f in bad:                                         # {{x}} desconhecido no texto vira texto literal
        for k in ("technique", "findings", "conclusion"):
            conv[k] = conv[k].replace("{{" + f + "}}", "[" + f + "]")
    if bad:
        conv["issues"].append(f"Campos não reconhecidos viraram texto: {', '.join(bad)}.")
    with c.session() as s:
        t, v = tpl.save(s, name=(name or conv["name"] or "Modelo importado").strip()[:120], modality=modality,
                        technique=conv["technique"], findings=conv["findings"], conclusion=conv["conclusion"],
                        **c.actor)
        v.import_report = {"issues": conv["issues"], "fields": conv["fields"], "header": conv["header"],
                           "footer": conv["footer"]}
        s.flush()
        from vyonix.audit import service as audit
        audit.record(s, action="report.template.import_docx", target_type="report_template", target_id=t.id,
                     details={"version": v.version, "issues": len(conv["issues"])}, **c.actor)
        return {"id": str(t.id), "version": v.version, "status": v.status, **v.import_report}


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
        blk = (item["draft"] or {}).get("signature_block") or item["signature_block"]
        data = pdf.preview(brand.effective(s, None), settings.get(s, "core", "institution"), body=text, block=blk)
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


# ------------------------------------------------------------------ imagem da assinatura manuscrita (T5)
def _sig_key(c: Ctx) -> bytes:
    from vyonix.secrets import SecretStore
    return SecretStore(c.plat.cfg.data_dir).get_or_create(sig.KEY_NAME)


class ConsentIn(BaseModel):
    allow: bool


class DelegateIn(BaseModel):
    user_id: uuid.UUID | None = None


async def _body(request: Request) -> bytes:
    from vyonix.errors import ValidationFailed
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > sig.MAX_BYTES:
            raise ValidationFailed("Imagem acima de 5 MB.")
    return bytes(data)


def _params(crop: str | None, brightness: float, contrast: float, remove_background: bool) -> dict:
    from vyonix.errors import ValidationFailed
    box = None
    if crop:
        try:
            box = tuple(float(x) for x in crop.split(","))
        except ValueError:
            raise ValidationFailed("Recorte inválido (use esquerda,topo,direita,base em frações).") from None
        if len(box) != 4:
            raise ValidationFailed("Recorte inválido (4 valores).")
    return {"crop": box, "brightness": brightness, "contrast": contrast, "remove_background": remove_background}


def _png(data: bytes):
    from fastapi.responses import Response
    return Response(data, media_type="image/png", headers={"Cache-Control": "no-store, private",
                                                           "X-Content-Type-Options": "nosniff"})


@router.get("/physicians/me/signature")
def my_signature(c: Ctx = Depends(needs("report.sign"))):
    """Situação e histórico da imagem do próprio médico."""
    with c.session() as s:
        return sig.status(s, c.p.user_id)


@router.post("/physicians/me/signature/preview")
async def preview_signature(request: Request, crop: str | None = None, brightness: float = 1.0, contrast: float = 1.0,
                            remove_background: bool = False, c: Ctx = Depends(needs("report.sign"))):
    """Tratamento sem gravar nada (para conferir antes de enviar)."""
    png, _w, _h = sig.process(await _body(request), **_params(crop, brightness, contrast, remove_background))
    return _png(png)


@router.post("/physicians/me/signature", status_code=201)
async def upload_signature(request: Request, crop: str | None = None, brightness: float = 1.0, contrast: float = 1.0,
                           remove_background: bool = False, c: Ctx = Depends(needs("report.sign"))):
    """Envia a imagem tratada: fica pendente até o médico confirmar."""
    data = await _body(request)
    with c.session() as s:
        sig.upload(s, c.p.user_id, data, key=_sig_key(c), actor=c.p.username, ip=c.ip,
                   **_params(crop, brightness, contrast, remove_background))
        return sig.status(s, c.p.user_id)


@router.get("/physicians/me/signature/image")
def my_signature_image(which: str = "active", c: Ctx = Depends(needs("report.sign"))):
    """A própria imagem (ativa ou pendente), só para o médico dono; nunca há URL pública."""
    with c.session() as s:
        return _png(sig.image_for(s, c.p.user_id, which=which, key=_sig_key(c), actor=c.p.username, ip=c.ip))


@router.post("/physicians/me/signature/confirm")
def confirm_signature(body: SignIn, c: Ctx = Depends(needs("report.sign"))):
    """O médico confirma, com a senha, que a imagem pendente é a assinatura dele (ativa e substitui a anterior)."""
    with c.session() as s:
        ok = auth.confirm_password(s, c.p, body.password, purpose="report.signature.confirm", ip=c.ip)
    if not ok:
        raise Forbidden("Senha incorreta: a imagem não foi ativada.", code="password_mismatch")
    with c.session() as s:
        sig.confirm(s, c.p.user_id, actor=c.p.username, ip=c.ip)
        return sig.status(s, c.p.user_id)


@router.delete("/physicians/me/signature")
def delete_signature(c: Ctx = Depends(needs("report.sign"))):
    with c.session() as s:
        sig.delete(s, c.p.user_id, actor=c.p.username, ip=c.ip)
        return sig.status(s, c.p.user_id)


@router.post("/physicians/me/signature/consent")
def signature_consent(body: ConsentIn, c: Ctx = Depends(needs("report.sign"))):
    with c.session() as s:
        sig.set_consent(s, c.p.user_id, body.allow, actor=c.p.username, ip=c.ip)
        return sig.status(s, c.p.user_id)


@router.get("/physicians/me/signature/delegates")
def signature_delegates(c: Ctx = Depends(needs("report.sign"))):
    with c.session() as s:
        return {"items": sig.delegate_candidates(s, exclude=c.p.user_id)}


@router.put("/physicians/me/signature/delegate")
def signature_delegate(body: DelegateIn, c: Ctx = Depends(needs("report.sign"))):
    with c.session() as s:
        sig.set_delegate(s, c.p.user_id, body.user_id, actor=c.p.username, ip=c.ip)
        return sig.status(s, c.p.user_id)


@router.post("/physicians/{pid}/signature/preview")
async def admin_preview_signature(pid: uuid.UUID, request: Request, crop: str | None = None, brightness: float = 1.0,
                                  contrast: float = 1.0, remove_background: bool = False,
                                  c: Ctx = Depends(needs("report.physicians.manage"))):
    png, _w, _h = sig.process(await _body(request), **_params(crop, brightness, contrast, remove_background))
    return _png(png)


@router.post("/physicians/{pid}/signature", status_code=201)
async def admin_upload_signature(pid: uuid.UUID, request: Request, crop: str | None = None, brightness: float = 1.0,
                                 contrast: float = 1.0, remove_background: bool = False,
                                 c: Ctx = Depends(needs("report.physicians.manage"))):
    """Envio pelo administrador **designado pelo próprio médico**; fica pendente até o médico confirmar."""
    data = await _body(request)
    with c.session() as s:
        img = sig.upload(s, c.p.user_id, data, key=_sig_key(c), actor=c.p.username, ip=c.ip, physician_id=pid,
                         **_params(crop, brightness, contrast, remove_background))
        return {"status": img.status, "uploaded_at": img.created_at.isoformat()}


@router.get("/physicians/{pid}/signature/pending")
def admin_view_signature(pid: uuid.UUID, c: Ctx = Depends(needs("report.physicians.manage"))):
    """O administrador designado vê só a imagem pendente que ele enviou (visualização auditada)."""
    with c.session() as s:
        return _png(sig.image_for(s, c.p.user_id, physician_id=pid, key=_sig_key(c), actor=c.p.username, ip=c.ip))


# ------------------------------------------------------------------ fila de telelaudo (T7)
class AssignIn(BaseModel):
    study_id: uuid.UUID
    physician_id: uuid.UUID
    priority: str = "routine"


@router.post("/assignments", status_code=201)
def assign(body: AssignIn, c: Ctx = Depends(needs("report.assign"))):
    from vyonix.report import queue
    with c.session() as s:
        a = queue.assign(s, body.study_id, body.physician_id, priority=body.priority, **c.actor)
        return {"id": str(a.id), "due_at": a.due_at.isoformat()}


@router.get("/assignable-physicians")
def assignable(c: Ctx = Depends(needs("report.assign"))):
    with c.session() as s:
        return {"items": [{"id": p["id"], "name": p["identification"]} for p in phys.listing(s) if p["active"]]}


# ------------------------------------------------------------------ saídas padronizadas opcionais (T8)
def _pdf_bytes(c: Ctx, s, rid: uuid.UUID) -> bytes:
    data, _ = rep.pdf(s, rid, signature_key=_sig_key(c), **c.actor)
    return data


@router.get("/reports/{rid}/fhir")
def export_fhir(rid: uuid.UUID, with_pdf: bool = True, c: Ctx = Depends(needs("report.read"))):
    from vyonix.report import interop
    with c.session() as s:
        _in_scope(c, s, report_id=rid)
        return interop.fhir(s, rid, pdf=_pdf_bytes(c, s, rid) if with_pdf else None, **c.actor)


@router.get("/reports/{rid}/hl7")
def export_hl7(rid: uuid.UUID, c: Ctx = Depends(needs("report.read"))):
    from fastapi.responses import Response
    from vyonix.report import interop
    from vyonix.settings import service as settings
    with c.session() as s:
        _in_scope(c, s, report_id=rid)
        inst = settings.get(s, "core", "institution").get("display_name") or ""
        msg = interop.hl7_oru(s, rid, sending_facility=inst, **c.actor)
    return Response(msg.encode("utf-8"), media_type="x-application/hl7-v2+er7; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="laudo.hl7"'})


@router.post("/reports/{rid}/send-to-pacs")
def send_to_pacs(rid: uuid.UUID, c: Ctx = Depends(needs("report.write"))):
    """Guarda o laudo liberado no PACS do VYONIX como DICOM Encapsulated PDF, no mesmo estudo (opcional)."""
    from sqlalchemy import select
    from vyonix.audit import service as audit
    from vyonix.clinical.models import Study
    from vyonix.errors import Conflict
    from vyonix.pacs import backend_for
    from vyonix.pacs import service as pacs
    from vyonix.pacs.models import PacsStudy
    from vyonix.report import interop
    from vyonix.report.models import Report
    with c.session() as s:
        _in_scope(c, s, report_id=rid)
        if not registry.is_enabled(s, "pacs"):
            raise Conflict("O VYONIX PACS não está habilitado nesta organização.")
        r = s.get(Report, rid)
        st = s.get(Study, r.study_id) if r else None
        ps = s.execute(select(PacsStudy).where(PacsStudy.study_uid == st.study_instance_uid)).scalar_one_or_none() \
            if st else None
        if ps is None:
            raise Conflict("O estudo deste laudo não está no PACS.")
        backend = backend_for(c.plat)
        if backend is None:
            raise Conflict("Motor DICOM não configurado.")
        data = interop.dicom_pdf(s, rid, _pdf_bytes(c, s, rid), patient_id=ps.patient_id)  # mesmo Patient ID do PACS
        res = pacs.ingest(s, backend, data, via="stow", **c.actor)
        audit.record(s, action="report.export.dicom", target_type="report", target_id=rid,
                     details={"duplicate": bool(res.duplicate)}, **c.actor)
        return {"sop_instance_uid": res.sop_uid, "series_instance_uid": res.series_uid, "duplicate": bool(res.duplicate)}
