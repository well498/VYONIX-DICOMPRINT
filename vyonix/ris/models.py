"""Agendamentos do RIS (por organização, com row level security)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from vyonix.db.base import Base, TenantMixin

SCHEMA = {"schema": "ris"}
STATUSES = ("scheduled", "in_progress", "received", "completed", "cancelled")


class Schedule(TenantMixin, Base):
    """Passo de procedimento agendado (DICOM Scheduled Procedure Step) de um pedido."""
    __tablename__ = "schedules"
    __table_args__ = (Index("uq_ris_schedules_sps", "tenant_id", "sps_id", unique=True),
                      Index("uq_ris_schedules_study_uid", "tenant_id", "study_instance_uid", unique=True),
                      Index("ix_ris_schedules_when", "tenant_id", "scheduled_at"), SCHEMA)
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("clinical.orders.id"), nullable=False, index=True)
    sps_id: Mapped[str] = mapped_column(String(16), nullable=False)
    study_instance_uid: Mapped[str] = mapped_column(String(64), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    modality: Mapped[str] = mapped_column(String(16), nullable=False)
    station_aet: Mapped[str | None] = mapped_column(String(16))
    room: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="scheduled")
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
