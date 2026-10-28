"""RIS: agendamentos e worklist (primeira entrega). Agendar exige o módulo RIS habilitado e licenciado."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from vyonix.api.app import Ctx, needs
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
    duration_min: int = Field(15, ge=1, le=480)


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


@router.get("/stations")
def stations(c: Ctx = Depends(needs("ris.schedule.manage"))):
    """Estações cadastradas no PACS que podem consultar a worklist (para escolher o AE Title no agendamento)."""
    from vyonix.pacs import service as pacs
    with c.session() as s:
        return {"items": [{"ae_title": n["ae_title"], "description": n["description"]}
                          for n in pacs.nodes(s) if n["can_query"]]}


@router.patch("/schedules/{sid}/status")
def status(sid: uuid.UUID, body: StatusIn, c: Ctx = Depends(needs("ris.schedule.manage"))):
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
