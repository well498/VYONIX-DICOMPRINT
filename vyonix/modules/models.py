from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from vyonix.db.base import Base, TenantMixin


class ModuleState(TenantMixin, Base):
    __tablename__ = "modules"
    __table_args__ = (Index("uq_modules_tenant_code", "tenant_id", "code", unique=True), {"schema": "platform"})
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="installed")   # installed|enabled|disabled
    changed_by: Mapped[str | None] = mapped_column(String(120))
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
