from __future__ import annotations

import uuid

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from vyonix.db.base import Base, TenantMixin


class Setting(TenantMixin, Base):
    __tablename__ = "settings"
    __table_args__ = (Index("uq_settings_scope_key", "tenant_id", "module", "site_id", "key", unique=True,
                            postgresql_nulls_not_distinct=True), {"schema": "platform"})
    module: Mapped[str] = mapped_column(String(30), nullable=False)
    site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tenancy.sites.id"))
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[object] = mapped_column(JSON, nullable=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class SettingHistory(TenantMixin, Base):
    __tablename__ = "settings_history"
    __table_args__ = (Index("ix_settings_history_scope", "tenant_id", "module", "key"), {"schema": "platform"})
    module: Mapped[str] = mapped_column(String(30), nullable=False)
    site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    old_value: Mapped[object] = mapped_column(JSON, nullable=True)
    new_value: Mapped[object] = mapped_column(JSON, nullable=True)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
