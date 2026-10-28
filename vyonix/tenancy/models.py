from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from vyonix.db.base import Base, TenantMixin


class Organization(TenantMixin, Base):
    """Cliente (clínica, hospital, empresa de telelaudo). ``tenant_id`` = o próprio ``id``."""
    __tablename__ = "organizations"
    __table_args__ = (Index("uq_organizations_code", "code", unique=True), {"schema": "tenancy"})
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    document: Mapped[str | None] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="institution",
                                      server_default="institution")       # institution | operator (VYONIX)
    institution_type: Mapped[str | None] = mapped_column(String(20))       # clinica | hospital | cdi | telelaudo
    legal_name: Mapped[str | None] = mapped_column(String(200))
    contact_name: Mapped[str | None] = mapped_column(String(120))
    contact_email: Mapped[str | None] = mapped_column(String(200))
    contact_phone: Mapped[str | None] = mapped_column(String(40))
    contracted_modules: Mapped[list | None] = mapped_column(JSON)          # intenção do contrato (não é licença)
    status_reason: Mapped[str | None] = mapped_column(String(300))


class Site(TenantMixin, Base):
    __tablename__ = "sites"
    __table_args__ = (Index("uq_sites_tenant_name", "tenant_id", "name", unique=True), {"schema": "tenancy"})
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    cnes: Mapped[str | None] = mapped_column(String(10))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="America/Sao_Paulo")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Installation(TenantMixin, Base):
    """Servidor EDGE ou ambiente CLOUD (identidade da instalação do licenciamento)."""
    __tablename__ = "installations"
    __table_args__ = (Index("uq_installations_installation_id", "installation_id", unique=True),
                      {"schema": "tenancy"})
    site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tenancy.sites.id"))
    installation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    hardware_id: Mapped[str | None] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(10), nullable=False, default="edge")
    version: Mapped[str | None] = mapped_column(String(40))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
