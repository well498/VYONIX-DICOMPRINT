"""Laudos, versões liberadas e modelos (por organização, com row level security)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from vyonix.db.base import Base, TenantMixin

SCHEMA = {"schema": "report"}
STATUSES = ("draft", "final")


class ReportTemplate(TenantMixin, Base):
    __tablename__ = "templates"
    __table_args__ = (Index("uq_report_templates_name", "tenant_id", "name", unique=True), SCHEMA)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    modality: Mapped[str | None] = mapped_column(String(16))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)


class Report(TenantMixin, Base):
    __tablename__ = "reports"
    __table_args__ = (Index("uq_report_reports_study", "tenant_id", "study_id", unique=True), SCHEMA)
    study_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("clinical.studies.id"), nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("clinical.orders.id"))
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="draft")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    critical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    critical_note: Mapped[str | None] = mapped_column(String(300))
    author: Mapped[str] = mapped_column(String(120), nullable=False)
    finalized_by: Mapped[str | None] = mapped_column(String(120))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)          # versões liberadas


class CriticalAlert(TenantMixin, Base):
    """Achado crítico a comunicar: aberto na liberação, encerrado com o registro da comunicação."""
    __tablename__ = "critical_alerts"
    __table_args__ = (Index("ix_report_critical_open", "tenant_id", "status"), SCHEMA)
    report_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("report.reports.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="open")       # open | communicated
    notified_to: Mapped[str | None] = mapped_column(String(200))
    channel: Mapped[str | None] = mapped_column(String(40))
    ack_note: Mapped[str | None] = mapped_column(String(500))
    ack_by: Mapped[str | None] = mapped_column(String(120))
    ack_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReportVersion(TenantMixin, Base):
    """Versão liberada (laudo ou adendo): imutável, com SHA-256 do conteúdo canônico."""
    __tablename__ = "report_versions"
    __table_args__ = (Index("uq_report_versions", "tenant_id", "report_id", "version", unique=True), SCHEMA)
    report_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("report.reports.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)                     # final | addendum
    body: Mapped[str] = mapped_column(Text, nullable=False)
    critical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    signed_by: Mapped[str] = mapped_column(String(120), nullable=False)
    signed_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
