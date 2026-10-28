"""Laudos, versões liberadas e modelos (por organização, com row level security)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, Uuid
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


class Physician(TenantMixin, Base):
    """Médico da organização (TELELAUDO T1): ligado a um usuário do VYONIX; CRM/UF únicos na organização."""
    __tablename__ = "physicians"
    __table_args__ = (Index("uq_report_physicians_user", "tenant_id", "user_id", unique=True),
                      Index("uq_report_physicians_crm", "tenant_id", "crm", "crm_uf", unique=True), SCHEMA)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("auth.users.id"), nullable=False)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    crm: Mapped[str] = mapped_column(String(10), nullable=False)
    crm_uf: Mapped[str] = mapped_column(String(2), nullable=False)
    rqe: Mapped[str | None] = mapped_column(String(40))
    specialties: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    footer: Mapped[str | None] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class PhysicianLink(TenantMixin, Base):
    """Vínculo do médico com a organização inteira (``site_id`` nulo) ou com uma unidade, com vigência."""
    __tablename__ = "physician_links"
    __table_args__ = SCHEMA
    physician_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("report.physicians.id"), nullable=False, index=True)
    site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tenancy.sites.id"))
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
