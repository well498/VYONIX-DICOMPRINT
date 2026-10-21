from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from vyonix.db.base import Base, TenantMixin


class Entitlement(TenantMixin, Base):
    """Direito vigente de um módulo, derivado do documento assinado mais recente."""
    __tablename__ = "entitlements"
    __table_args__ = (Index("uq_entitlements_module", "tenant_id", "module", unique=True), {"schema": "licensing"})
    module: Mapped[str] = mapped_column(String(30), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)        # subscription | demo | permanent
    plan: Mapped[str | None] = mapped_column(String(20))
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    demo_days: Mapped[int | None] = mapped_column(Integer)
    activate_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    limits: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    license_id: Mapped[str] = mapped_column(String(40), nullable=False)
    grant_id: Mapped[str] = mapped_column(String(60), nullable=False)       # identifica o direito (prorrogação)


class LicenseDocument(TenantMixin, Base):
    __tablename__ = "license_documents"
    __table_args__ = (Index("uq_license_documents_sha", "tenant_id", "sha256", unique=True), {"schema": "licensing"})
    kind: Mapped[str] = mapped_column(String(20), nullable=False)          # license | authorization
    license_id: Mapped[str] = mapped_column(String(40), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    document: Mapped[str] = mapped_column(Text, nullable=False)
    applied_by: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")      # active | superseded
