"""RIS: agendamentos e worklist (primeira entrega). Agendar exige o módulo RIS habilitado e licenciado."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from vyonix.api.app import Ctx, needs
from vyonix.api.app import ctx as ctx_any
from vyonix.auth import scope
from vyonix.errors import NotLicensed
from vyonix.modules import registry
from vyonix.ris import service as ris

router = APIRouter(prefix="/ris")


class ScheduleIn(BaseModel):
    order_id: uuid.UUID
    scheduled_at: datetime
    modality: str | None = Field(None, max_length=16)
    station_aet: str | None = Field(None, max_length=16)
    room: str | None = Field(None, max_length=64)
    description: str | None = Field(None, max_length=64)
    duration_min: int | None = Field(None, ge=1, le=480)


class StatusIn(BaseModel):
    status: str
    reason: str | None = Field(None, max_length=300)


def _require(c: Ctx, s) -> None:
    if not registry.is_enabled(s, "ris"):
        raise NotLicensed("O módulo VYONIX RIS não está habilitado nesta organização.", code="module_disabled")


@router.post("/schedules", status_code=201)
def create(body: ScheduleIn, c: Ctx = Depends(needs("ris.schedule.manage"))):
    with c.session() as s:
        _require(c, s)
        _order_site(c, s, body.order_id, "ris.schedule.manage")        # P0 0.3.2: pedido de outra unidade → 404
        st = ris.schedule(s, body.order_id, scheduled_at=body.scheduled_at, modality=body.modality,
                          station_aet=body.station_aet, room=body.room, description=body.description,
                          duration_min=body.duration_min, **c.actor)
        return {"id": str(st.id), "sps_id": st.sps_id, "study_instance_uid": st.study_instance_uid,
                "status": st.status}


def _order_site(c: Ctx, s, order_id: uuid.UUID, *perms: str):
    """P0 0.3.2: a unidade do pedido (ou do atendimento) precisa estar entre as do papel; sem unidade, só global."""
    from vyonix.clinical import service as clinical
    from vyonix.clinical.models import Order
    from vyonix.errors import NotFound
    o = s.get(Order, order_id)
    if o is None:
        raise NotFound("Pedido não encontrado.")
    site = clinical.order_site(s, o)
    if not scope.can(c.p, perms, site):
        scope.deny(c, "order", o.id, perms, "no_site" if site is None else "site_scope", not_found=True)
    return o


@router.get("/orders")
def pending(c: Ctx = Depends(needs("ris.schedule.manage"))):
    with c.session() as s:
        return {"items": ris.pending_orders(s, sites=scope.sites(c.p, "ris.schedule.manage"))}


class RoomIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    modality: str | None = Field(None, max_length=16)
    station_aet: str | None = Field(None, max_length=16)
    default_duration_min: int = Field(15, ge=1, le=480)
    active: bool = True


@router.get("/rooms")
def list_rooms(include_inactive: bool = False, c: Ctx = Depends(needs("ris.schedule.read"))):
    with c.session() as s:
        return {"items": ris.rooms(s, include_inactive=include_inactive)}


@router.post("/rooms", status_code=201)
def create_room(body: RoomIn, c: Ctx = Depends(needs("ris.rooms.manage"))):
    with c.session() as s:
        return {"id": str(ris.save_room(s, **body.model_dump(), **c.actor).id)}


@router.put("/rooms/{rid}")
def update_room(rid: uuid.UUID, body: RoomIn, c: Ctx = Depends(needs("ris.rooms.manage"))):
    with c.session() as s:
        return {"id": str(ris.save_room(s, room_id=rid, **body.model_dump(), **c.actor).id)}


@router.get("/stations")
def stations(c: Ctx = Depends(needs("ris.schedule.manage"))):
    """Estações cadastradas no PACS que podem consultar a worklist (para escolher o AE Title no agendamento)."""
    from vyonix.pacs import service as pacs
    with c.session() as s:
        return {"items": [{"ae_title": n["ae_title"], "description": n["description"]}
                          for n in pacs.nodes(s) if n["can_query"]]}


@router.patch("/schedules/{sid}/status")
def status(sid: uuid.UUID, body: StatusIn, c: Ctx = Depends(needs("ris.schedule.read"))):
    """Agendamento (recepção) muda qualquer situação; o técnico (``ris.exam.perform``) registra chegada, início e
    conclusão — cancelar continua com quem agenda."""
    from vyonix.errors import Forbidden
    if not c.p.has("ris.schedule.manage") and not (c.p.has("ris.exam.perform") and
                                                   body.status in ("arrived", "in_progress", "completed")):
        raise Forbidden("Sem permissão para esta mudança de situação.", code="forbidden")
    with c.session() as s:
        from vyonix.ris.models import Schedule
        sc_ = s.get(Schedule, sid)
        if sc_ is not None:                     # P0 0.3.2: agendamento de outra unidade → 404
            _order_site(c, s, sc_.order_id, "ris.schedule.manage", "ris.exam.perform")
        st = ris.set_status(s, sid, body.status, reason=body.reason, **c.actor)
        return {"id": str(st.id), "status": st.status}


@router.get("/worklist")
def worklist(date_from: date | None = None, date_to: date | None = None, modality: str | None = None,
             station_aet: str | None = None, include_done: bool = False,
             c: Ctx = Depends(needs("ris.schedule.read"))):
    with c.session() as s:
        return {"items": ris.worklist(s, date_from=date_from, date_to=date_to, modality=modality,
                                      station_aet=station_aet, include_done=include_done,
                                      sites=scope.sites(c.p, "ris.schedule.read"))}


@router.get("/exam-center")
def exam_center(date_from: date, date_to: date, modality: str | None = None, stage: str | None = None,
                late_only: bool = False, c: Ctx = Depends(needs("ris.schedule.read"))):
    """Central de exames: ciclo de cada pedido do período, atrasos e tempos (somente leitura)."""
    from vyonix.errors import ValidationFailed
    from vyonix.ris import tracking
    if date_to < date_from or (date_to - date_from).days > 62:
        raise ValidationFailed("Período inválido (até 62 dias).")
    if stage and stage not in tracking.STAGES:
        raise ValidationFailed("Etapa inválida.")
    with c.session() as s:
        return tracking.exam_center(s, date_from=date_from, date_to=date_to, modality=modality, stage=stage,
                                    late_only=late_only, sites=scope.sites(c.p, "ris.schedule.read"))


@router.get("/technician-panel")
def technician_panel(day: date | None = None, c: Ctx = Depends(needs("ris.schedule.read"))):
    """Painel do Técnico em Radiologia: exames do dia, estudos recebidos, recusas na recepção e pendências."""
    from vyonix.ris import technician
    with c.session() as s:
        return technician.panel(s, day=day, with_images=c.p.has("pacs.studies.read"),
                                sites=scope.sites(c.p, "ris.schedule.read"))


# ------------------------------------------------------------------ Central de Exames: preparação do estudo
from fastapi import Request  # noqa: E402


def _prep_reader(c: Ctx) -> None:
    """Técnico (preparação), coordenação, médicos e quem consulta a agenda leem a preparação."""
    from vyonix.errors import Forbidden
    if not any(c.p.has(x) for x in ("ris.exam.prepare", "ris.schedule.read", "report.read")):
        raise Forbidden("Sem permissão para a preparação de exames.", code="forbidden")


def _prep_scope(c: Ctx, s, study_id: uuid.UUID) -> None:
    """Médico só vê estudos da sua unidade ou compartilhados com ele (mesma regra da fila de laudos); os demais
    papéis respeitam a unidade do exame; exame sem unidade só para quem atua em todas (P0 0.3.2)."""
    from vyonix.clinical.models import Study
    from vyonix.errors import NotFound
    from vyonix.report import queue
    from vyonix.ris import prep
    if study_id in prep.shared_studies(s, c.p.user_id):
        return
    sc = queue.scope(s, c.p.user_id, can_assign=c.p.has("report.assign"))
    if sc is not None:
        st = s.get(Study, study_id)
        if st is None:
            raise NotFound("Exame não encontrado.")
        if not queue.allowed(sc, st.site_id):
            scope.deny(c, "study", st.id, "report.read", "no_site" if st.site_id is None else "physician_link",
                       physician=True)
        return
    _site(c, s, study_id, *_READ_PERMS)             # MISSÃO 2 R-04: não-médico também respeita a unidade


_READ_PERMS = ("ris.exam.prepare", "ris.schedule.read", "report.read", "report.assign")


def _site(c: Ctx, s, study_id: uuid.UUID, *perms: str):
    """O papel que concede a permissão precisa valer na unidade do exame (papel por unidade não alcança outra
    unidade — MISSÃO 2, R-04). P0 0.3.2 (regra 3 do proprietário): exame **sem unidade** fica restrito a quem tem a
    permissão em todas as unidades até a vinculação correta (substitui a exceção V-03)."""
    from vyonix.clinical.models import Study
    from vyonix.errors import NotFound
    st = s.get(Study, study_id)
    if st is None:
        raise NotFound("Exame não encontrado.")
    if not scope.can(c.p, perms, st.site_id):
        scope.deny(c, "study", st.id, perms, "no_site" if st.site_id is None else "site_scope")
    return st


def _att_key(c: Ctx) -> bytes:
    from vyonix.secrets import SecretStore
    from vyonix.ris import prep
    return SecretStore(c.plat.cfg.data_dir).get_or_create(prep.KEY_NAME)


class CheckIn(BaseModel):
    code: str = Field(min_length=2, max_length=30)
    done: bool = True


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class FlagIn(BaseModel):
    code: str = Field(min_length=2, max_length=30)
    note: str | None = Field(None, max_length=500)


class PriorityIn(BaseModel):
    priority: str
    reason: str = Field(min_length=3, max_length=300)          # justificativa obrigatória


class PhysicianChangeIn(BaseModel):
    physician_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=300)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1, max_length=300)


class DuplicateIn(BaseModel):
    duplicate_of: uuid.UUID | None = None
    note: str | None = Field(None, max_length=200)


class ShareIn(BaseModel):
    user_id: uuid.UUID
    scope: str = "view"
    hours: int = Field(24, ge=1, le=720)


@router.get("/prep")
def prep_queue(date_from: date | None = None, date_to: date | None = None, modality: str | None = None,
               station: str | None = None, site_id: uuid.UUID | None = None, stage: str | None = None,
               priority: str | None = None, patient: str | None = None, accession: str | None = None,
               c: Ctx = Depends(needs("ris.exam.prepare"))):
    from vyonix.ris import prep
    with c.session() as s:
        return prep.queue(s, c.p.user_id, date_from=date_from, date_to=date_to, modality=modality, station=station,
                          site_id=site_id, stage_filter=stage, priority=priority, patient=patient, accession=accession,
                          sites=scope.sites(c.p, "ris.exam.prepare"))


@router.get("/studies/{study_id}/timeline")
def study_timeline(study_id: uuid.UUID, c: Ctx = Depends(ctx_any)):
    """Linha do tempo do exame (etapas, horários e responsáveis), para quem pode ver a preparação do estudo."""
    from vyonix.ris import timeline
    _prep_reader(c)
    with c.session() as s:
        _prep_scope(c, s, study_id)
        return timeline.study_timeline(s, study_id)


def _study_ok_fn(c: Ctx, s):
    """Mesmo critério do ``_prep_scope``, sem recusar: compartilhado, vínculo do médico ou unidade do papel."""
    from vyonix.report import queue
    from vyonix.ris import prep
    shared = set(prep.shared_studies(s, c.p.user_id))
    sc = queue.scope(s, c.p.user_id, can_assign=c.p.has("report.assign"))

    def ok(st) -> bool:
        if st is None:
            return False
        if st.id in shared:
            return True
        if sc is not None:
            return queue.allowed(sc, st.site_id)
        return scope.can(c.p, _READ_PERMS, st.site_id)
    return ok


@router.get("/patients/{patient_id}/history")
def patient_history(patient_id: uuid.UUID, c: Ctx = Depends(needs("clinical.patients.read"))):
    """Histórico integrado do paciente (PACS, RIS e laudos), com as regras de acesso da preparação: exame de unidade
    sem vínculo aparece restrito."""
    from vyonix.report import queue
    from vyonix.ris import prep, timeline
    _prep_reader(c)
    with c.session() as s:
        from vyonix.clinical import service as clinical
        psites = scope.sites(c.p, "clinical.patients.read")
        if not clinical.patient_in_scope(s, patient_id, psites, allow_unlinked=False):
            scope.deny(c, "patient", patient_id, "clinical.patients.read", "patient_scope", not_found=True)
        out = timeline.patient_history(s, patient_id, study_ok=_study_ok_fn(c, s),
                                       shared=prep.shared_studies(s, c.p.user_id))
        out["can_view_images"] = c.p.has("pacs.studies.read")
        out["can_read_reports"] = c.p.has("report.read")
        return out


@router.get("/studies/{study_id}/priors")
def study_priors(study_id: uuid.UUID, c: Ctx = Depends(ctx_any)):
    """Exames anteriores do mesmo paciente (comparação), com as mesmas regras de acesso da preparação."""
    from vyonix.report import queue
    from vyonix.ris import timeline
    _prep_reader(c)
    with c.session() as s:
        _prep_scope(c, s, study_id)
        out = timeline.priors(s, study_id)
        ok_fn = _study_ok_fn(c, s)
        from vyonix.clinical.models import Study
        for it in out["items"]:                     # anterior fora do escopo: aparece sem acesso ao conteúdo
            ok = ok_fn(s.get(Study, uuid.UUID(it["study_id"])))
            if not ok:
                it.update(study_instance_uid=None, report=None, description=None, accession=None, restricted=True)
        return out


@router.get("/prep/{study_id}")
def prep_detail(study_id: uuid.UUID, c: Ctx = Depends(ctx_any)):
    from vyonix.ris import prep
    _prep_reader(c)
    with c.session() as s:
        _prep_scope(c, s, study_id)
        out = prep.detail(s, study_id, c.p.user_id, visible=_study_ok_fn(c, s))
        _st_site = s.get(__import__("vyonix.clinical.models", fromlist=["Study"]).Study, study_id).site_id
        out["can"] = {k: scope.can(c.p, p, _st_site) for k, p in (("prepare", "ris.exam.prepare"), ("priority", "ris.exam.priority"),
                                                   ("cancel", "ris.exam.cancel"), ("share", "ris.exam.share"),
                                                   ("assign", "report.assign"), ("return", "report.write"),
                                                   ("viewer", "pacs.studies.read"))}
        from vyonix.clinical.models import Study
        from vyonix.ris import exclusive
        tech = exclusive.is_technician(c.p, s.get(Study, study_id).site_id)
        locked = bool(out.get("changes_locked"))
        # trocar médico / prioridade: exclusivo do Técnico em Radiologia e só antes do início do laudo
        out["can"]["priority"] = out["can"]["change_physician"] = tech and not locked
        out["can"]["assign"] = False
        out["can"]["technician"] = tech
        out["can"]["request_change"] = False
        return out


@router.post("/prep/{study_id}/read")
def prep_mark_read(study_id: uuid.UUID, c: Ctx = Depends(ctx_any)):
    from vyonix.ris import prep
    _prep_reader(c)
    with c.session() as s:
        _prep_scope(c, s, study_id)
        prep.mark_read(s, study_id, c.p.user_id)
    return {"ok": True}


@router.post("/prep/{study_id}/check")
def prep_check(study_id: uuid.UUID, body: CheckIn, c: Ctx = Depends(needs("ris.exam.prepare"))):
    from vyonix.ris import prep
    with c.session() as s:
        _require(c, s)                     # módulo RIS habilitado e licenciado
        _site(c, s, study_id, "ris.exam.prepare")
        prep.set_check(s, study_id, body.code, body.done, **c.actor)
        return prep.detail(s, study_id, c.p.user_id, visible=_study_ok_fn(c, s))


@router.post("/prep/{study_id}/comments", status_code=201)
def prep_comment(study_id: uuid.UUID, body: TextIn, c: Ctx = Depends(ctx_any)):
    from vyonix.ris import prep
    _prep_reader(c)
    with c.session() as s:
        _require(c, s)                     # módulo RIS habilitado e licenciado
        _prep_scope(c, s, study_id)
        cm = prep.add_comment(s, study_id, body.text, **c.actor)
        return {"id": str(cm.id)}


@router.post("/prep/{study_id}/flags", status_code=201)
def prep_flag(study_id: uuid.UUID, body: FlagIn, c: Ctx = Depends(ctx_any)):
    """Suspeita técnica (técnico) ou pedido de troca de médico/prioridade (técnico ou médico)."""
    from vyonix.errors import Forbidden
    from vyonix.ris import prep
    if not (c.p.has("ris.exam.prepare") or (c.p.has("report.read") and body.code in prep.REQUESTS + ("other",))):
        raise Forbidden("Sem permissão para registrar esta sinalização.", code="forbidden")
    with c.session() as s:
        _require(c, s)                     # módulo RIS habilitado e licenciado
        _prep_scope(c, s, study_id)
        from vyonix.clinical.models import Study
        site = s.get(Study, study_id).site_id         # P0 0.3.2 (R13): a permissão vale na unidade do exame
        if not (scope.can(c.p, "ris.exam.prepare", site) or
                (scope.can(c.p, "report.read", site) and body.code in prep.REQUESTS + ("other",))):
            scope.deny(c, "study", study_id, "ris.exam.prepare", "no_site" if site is None else "site_scope")
        f = prep.add_flag(s, study_id, body.code, body.note, **c.actor)
        return {"id": str(f.id)}


@router.post("/prep/flags/{flag_id}/resolve")
def prep_flag_resolve(flag_id: uuid.UUID, c: Ctx = Depends(needs("ris.exam.prepare"))):
    from vyonix.ris import prep
    with c.session() as s:
        _require(c, s)                     # módulo RIS habilitado e licenciado
        from vyonix.ris.models import ExamFlag
        f = s.get(ExamFlag, flag_id)
        if f is not None:
            _site(c, s, f.study_id, "ris.exam.prepare")
        prep.resolve_flag(s, flag_id, **c.actor)
    return {"ok": True}


@router.post("/prep/{study_id}/attachments", status_code=201)
async def prep_attach(study_id: uuid.UUID, request: Request, kind: str = "document", filename: str | None = None,
                      c: Ctx = Depends(needs("ris.exam.prepare"))):
    from vyonix.errors import ValidationFailed
    from vyonix.ris import prep
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > prep.MAX_AUDIO:
            raise ValidationFailed("Arquivo acima do tamanho permitido.")
    with c.session() as s:
        _require(c, s)                     # módulo RIS habilitado e licenciado
        _site(c, s, study_id, "ris.exam.prepare")
        a = prep.add_attachment(s, study_id, bytes(data), kind=kind, filename=filename, key=_att_key(c), **c.actor)
        return {"id": str(a.id), "media_type": a.media_type}


@router.get("/prep/attachments/{attachment_id}")
def prep_attachment(attachment_id: uuid.UUID, c: Ctx = Depends(ctx_any)):
    from fastapi.responses import Response
    from vyonix.ris import prep
    from vyonix.ris.models import ExamAttachment
    _prep_reader(c)
    with c.session() as s:
        a = s.get(ExamAttachment, attachment_id)
        if a is not None:
            _prep_scope(c, s, a.study_id)
        data, a = prep.read_attachment(s, attachment_id, key=_att_key(c), **c.actor)
    safe = "".join(ch for ch in a.filename if ch.isalnum() or ch in "._- ")[:80] or "anexo"
    return Response(data, media_type=a.media_type, headers={
        "Content-Disposition": f'inline; filename="{safe}"', "Cache-Control": "no-store, private",
        "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; sandbox"})


def _tech_study(c: Ctx, s, study_id: uuid.UUID, action: str):
    """Exclusivo do Técnico em Radiologia (papel ``tecnico`` na unidade do exame); outros papéis não concedem."""
    from vyonix.clinical.models import Study
    from vyonix.errors import NotFound
    from vyonix.ris import exclusive
    st = s.get(Study, study_id)
    if st is None:
        raise NotFound("Exame não encontrado.")
    from vyonix.errors import Forbidden
    try:
        exclusive.require(c.p, st.site_id, action=action)
    except Forbidden as exc:                      # P0 0.3.2: recusa auditada (access.denied)
        reason = "no_site" if st.site_id is None else (
            "site_scope" if any(r.get("role") == exclusive.ROLE for r in c.p.roles) else "technician_only")
        raise scope.attach(exc, c, "study", st.id, f"ris.exam.{action}", reason)
    _prep_scope(c, s, study_id)
    return st


@router.post("/prep/{study_id}/priority")
def prep_priority(study_id: uuid.UUID, body: PriorityIn, c: Ctx = Depends(ctx_any)):
    from vyonix.ris import prep
    with c.session() as s:
        _require(c, s)                     # módulo RIS habilitado e licenciado
        _tech_study(c, s, study_id, "prioridade")
        return {"priority": prep.set_priority(s, study_id, body.priority, reason=body.reason, **c.actor)}


@router.get("/prep/{study_id}/eligible-physicians")
def prep_eligible(study_id: uuid.UUID, c: Ctx = Depends(ctx_any)):
    """Médicos habilitados na unidade do exame (para o Técnico em Radiologia trocar o médico)."""
    from vyonix.report import distribution
    with c.session() as s:
        _require(c, s)
        st = _tech_study(c, s, study_id, "trocar_medico")
        return {"items": [{"id": str(p.id), "name": p.full_name} for p in distribution.eligible(s, st)]}


@router.post("/prep/{study_id}/physician")
def prep_change_physician(study_id: uuid.UUID, body: PhysicianChangeIn, c: Ctx = Depends(ctx_any)):
    """Trocar médico — só o Técnico em Radiologia, só antes do início do laudo, com justificativa (auditado)."""
    from vyonix.ris import prep
    from vyonix.report import queue
    with c.session() as s:
        _require(c, s)
        st = _tech_study(c, s, study_id, "trocar_medico")
        pr = prep.priority_of(s, st, prep._prep(s, study_id, create=False))
        a = queue.assign(s, study_id, body.physician_id, priority=pr, reason=body.reason, **c.actor)
        return {"assignment_id": str(a.id), "due_at": a.due_at.isoformat()}


@router.post("/prep/{study_id}/duplicate")
def prep_duplicate(study_id: uuid.UUID, body: DuplicateIn, c: Ctx = Depends(needs("ris.exam.prepare"))):
    from vyonix.ris import prep
    with c.session() as s:
        _require(c, s)                     # módulo RIS habilitado e licenciado
        _site(c, s, study_id, "ris.exam.prepare")
        if body.duplicate_of is not None:              # P0 0.3.2 (R16): o outro estudo também precisa estar no escopo
            _site(c, s, body.duplicate_of, "ris.exam.prepare")
        prep.decide_duplicate(s, study_id, duplicate_of=body.duplicate_of, note=body.note, **c.actor)
        return prep.detail(s, study_id, c.p.user_id, visible=_study_ok_fn(c, s))


@router.post("/prep/{study_id}/forward")
def prep_forward(study_id: uuid.UUID, c: Ctx = Depends(needs("ris.exam.prepare"))):
    from vyonix.ris import prep
    with c.session() as s:
        _require(c, s)                     # módulo RIS habilitado e licenciado
        _site(c, s, study_id, "ris.exam.prepare")
        return prep.forward(s, study_id, **c.actor)


def _return_allowed(c: Ctx, s, study_id: uuid.UUID) -> None:
    """Devolver para correção encerra a atribuição: só o médico responsável pelo exame (ou quem distribui, com
    ``report.assign``) — médico de outro exame não devolve (MISSÃO 2, R-03)."""
    from vyonix.errors import Forbidden
    from vyonix.report import authorship
    from vyonix.report.models import Physician
    from sqlalchemy import select as _select
    if c.p.has("report.assign"):
        return
    resp = authorship.responsible(s, study_id)
    if resp is None:
        return
    me = s.execute(_select(Physician).where(Physician.user_id == c.p.user_id)).scalar_one_or_none()
    if me is None or me.id != resp:
        raise Forbidden(authorship.MESSAGE, code=authorship.CODE, details={"action": "devolver"})


@router.post("/prep/{study_id}/return")
def prep_return(study_id: uuid.UUID, body: ReasonIn, c: Ctx = Depends(needs("report.write"))):
    from vyonix.ris import prep
    with c.session() as s:
        _require(c, s)                     # módulo RIS habilitado e licenciado
        _prep_scope(c, s, study_id)
        _return_allowed(c, s, study_id)
        prep.return_for_correction(s, study_id, body.reason, **c.actor)
    return {"ok": True}


@router.post("/prep/{study_id}/cancel")
def prep_cancel(study_id: uuid.UUID, body: ReasonIn, c: Ctx = Depends(needs("ris.exam.cancel"))):
    from vyonix.ris import prep
    with c.session() as s:
        _require(c, s)                     # módulo RIS habilitado e licenciado
        _site(c, s, study_id, "ris.exam.cancel")
        prep.cancel(s, study_id, body.reason, **c.actor)
    return {"ok": True}


@router.post("/prep/{study_id}/shares", status_code=201)
def prep_share(study_id: uuid.UUID, body: ShareIn, c: Ctx = Depends(needs("ris.exam.share"))):
    from vyonix.ris import prep
    with c.session() as s:
        _require(c, s)                     # módulo RIS habilitado e licenciado
        st = _site(c, s, study_id, "ris.exam.share")
        # P0 0.3.2 (R17): o destinatário precisa poder ver exames da unidade, salvo permissão global específica
        if not scope.user_can(s, body.user_id, _READ_PERMS, st.site_id) and \
                not c.p.global_has("ris.exam.share.cross_site"):
            from vyonix.errors import Conflict
            raise Conflict("O destinatário não atua na unidade deste exame.", code="share_out_of_site")
        sh = prep.share(s, study_id, body.user_id, scope=body.scope, hours=body.hours, **c.actor)
        return {"id": str(sh.id), "expires_at": sh.expires_at.isoformat()}


@router.delete("/prep/shares/{share_id}")
def prep_unshare(share_id: uuid.UUID, c: Ctx = Depends(needs("ris.exam.share"))):
    from vyonix.ris import prep
    with c.session() as s:
        _require(c, s)                     # módulo RIS habilitado e licenciado
        from vyonix.ris.models import ExamShare
        sh = s.get(ExamShare, share_id)
        if sh is not None:
            _site(c, s, sh.study_id, "ris.exam.share")
        else:
            from vyonix.errors import NotFound
            raise NotFound("Compartilhamento não encontrado.")
        prep.revoke_share(s, share_id, **c.actor)
    return {"ok": True}
