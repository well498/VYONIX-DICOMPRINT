"""RIS: agendamentos e worklist (primeira entrega). Agendar exige o módulo RIS habilitado e licenciado."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from vyonix.api.app import Ctx, needs
from vyonix.api.app import ctx as ctx_any
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
    c.plat.licensing.require_module(s, "ris")


@router.post("/schedules", status_code=201)
def create(body: ScheduleIn, c: Ctx = Depends(needs("ris.schedule.manage"))):
    with c.session() as s:
        _require(c, s)
        st = ris.schedule(s, body.order_id, scheduled_at=body.scheduled_at, modality=body.modality,
                          station_aet=body.station_aet, room=body.room, description=body.description,
                          duration_min=body.duration_min, **c.actor)
        return {"id": str(st.id), "sps_id": st.sps_id, "study_instance_uid": st.study_instance_uid,
                "status": st.status}


@router.get("/orders")
def pending(c: Ctx = Depends(needs("ris.schedule.manage"))):
    with c.session() as s:
        return {"items": ris.pending_orders(s)}


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
        st = ris.set_status(s, sid, body.status, reason=body.reason, **c.actor)
        return {"id": str(st.id), "status": st.status}


@router.get("/worklist")
def worklist(date_from: date | None = None, date_to: date | None = None, modality: str | None = None,
             station_aet: str | None = None, include_done: bool = False,
             c: Ctx = Depends(needs("ris.schedule.read"))):
    with c.session() as s:
        return {"items": ris.worklist(s, date_from=date_from, date_to=date_to, modality=modality,
                                      station_aet=station_aet, include_done=include_done)}


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
                                    late_only=late_only)


@router.get("/technician-panel")
def technician_panel(day: date | None = None, c: Ctx = Depends(needs("ris.schedule.read"))):
    """Painel do Técnico em Radiologia: exames do dia, estudos recebidos, recusas na recepção e pendências."""
    from vyonix.ris import technician
    with c.session() as s:
        return technician.panel(s, day=day, with_images=c.p.has("pacs.studies.read"))


# ------------------------------------------------------------------ Central de Exames: preparação do estudo
from fastapi import Request  # noqa: E402


def _prep_reader(c: Ctx) -> None:
    """Técnico (preparação), coordenação, médicos e quem consulta a agenda leem a preparação."""
    from vyonix.errors import Forbidden
    if not any(c.p.has(x) for x in ("ris.exam.prepare", "ris.schedule.read", "report.read")):
        raise Forbidden("Sem permissão para a preparação de exames.", code="forbidden")


def _prep_scope(c: Ctx, s, study_id: uuid.UUID) -> None:
    """Médico só vê estudos da sua unidade ou compartilhados com ele (mesma regra da fila de laudos)."""
    from vyonix.report import queue
    from vyonix.ris import prep
    if study_id in prep.shared_studies(s, c.p.user_id):
        return
    queue.require(s, queue.scope(s, c.p.user_id, can_assign=c.p.has("report.assign")), study_id)


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
    reason: str | None = Field(None, max_length=300)


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
                          site_id=site_id, stage_filter=stage, priority=priority, patient=patient, accession=accession)


@router.get("/prep/{study_id}")
def prep_detail(study_id: uuid.UUID, c: Ctx = Depends(ctx_any)):
    from vyonix.ris import prep
    _prep_reader(c)
    with c.session() as s:
        _prep_scope(c, s, study_id)
        out = prep.detail(s, study_id, c.p.user_id)
        out["can"] = {k: c.p.has(p) for k, p in (("prepare", "ris.exam.prepare"), ("priority", "ris.exam.priority"),
                                                   ("cancel", "ris.exam.cancel"), ("share", "ris.exam.share"),
                                                   ("assign", "report.assign"), ("return", "report.write"),
                                                   ("viewer", "pacs.studies.read"))}
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
        prep.set_check(s, study_id, body.code, body.done, **c.actor)
        return prep.detail(s, study_id, c.p.user_id)


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
        f = prep.add_flag(s, study_id, body.code, body.note, **c.actor)
        return {"id": str(f.id)}


@router.post("/prep/flags/{flag_id}/resolve")
def prep_flag_resolve(flag_id: uuid.UUID, c: Ctx = Depends(needs("ris.exam.prepare"))):
    from vyonix.ris import prep
    with c.session() as s:
        _require(c, s)                     # módulo RIS habilitado e licenciado
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


@router.post("/prep/{study_id}/priority")
def prep_priority(study_id: uuid.UUID, body: PriorityIn, c: Ctx = Depends(needs("ris.exam.priority"))):
    from vyonix.ris import prep
    with c.session() as s:
        _require(c, s)                     # módulo RIS habilitado e licenciado
        return {"priority": prep.set_priority(s, study_id, body.priority, reason=body.reason, **c.actor)}


@router.post("/prep/{study_id}/duplicate")
def prep_duplicate(study_id: uuid.UUID, body: DuplicateIn, c: Ctx = Depends(needs("ris.exam.prepare"))):
    from vyonix.ris import prep
    with c.session() as s:
        _require(c, s)                     # módulo RIS habilitado e licenciado
        prep.decide_duplicate(s, study_id, duplicate_of=body.duplicate_of, note=body.note, **c.actor)
        return prep.detail(s, study_id, c.p.user_id)


@router.post("/prep/{study_id}/forward")
def prep_forward(study_id: uuid.UUID, c: Ctx = Depends(needs("ris.exam.prepare"))):
    from vyonix.ris import prep
    with c.session() as s:
        _require(c, s)                     # módulo RIS habilitado e licenciado
        return prep.forward(s, study_id, **c.actor)


@router.post("/prep/{study_id}/return")
def prep_return(study_id: uuid.UUID, body: ReasonIn, c: Ctx = Depends(needs("report.write"))):
    from vyonix.ris import prep
    with c.session() as s:
        _require(c, s)                     # módulo RIS habilitado e licenciado
        _prep_scope(c, s, study_id)
        prep.return_for_correction(s, study_id, body.reason, **c.actor)
    return {"ok": True}


@router.post("/prep/{study_id}/cancel")
def prep_cancel(study_id: uuid.UUID, body: ReasonIn, c: Ctx = Depends(needs("ris.exam.cancel"))):
    from vyonix.ris import prep
    with c.session() as s:
        _require(c, s)                     # módulo RIS habilitado e licenciado
        prep.cancel(s, study_id, body.reason, **c.actor)
    return {"ok": True}


@router.post("/prep/{study_id}/shares", status_code=201)
def prep_share(study_id: uuid.UUID, body: ShareIn, c: Ctx = Depends(needs("ris.exam.share"))):
    from vyonix.ris import prep
    with c.session() as s:
        _require(c, s)                     # módulo RIS habilitado e licenciado
        sh = prep.share(s, study_id, body.user_id, scope=body.scope, hours=body.hours, **c.actor)
        return {"id": str(sh.id), "expires_at": sh.expires_at.isoformat()}


@router.delete("/prep/shares/{share_id}")
def prep_unshare(share_id: uuid.UUID, c: Ctx = Depends(needs("ris.exam.share"))):
    from vyonix.ris import prep
    with c.session() as s:
        _require(c, s)                     # módulo RIS habilitado e licenciado
        prep.revoke_share(s, share_id, **c.actor)
    return {"ok": True}
