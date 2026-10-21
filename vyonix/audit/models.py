from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Identity, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from vyonix.db.base import Base


class AuditEntry(Base):
    """Registro de auditoria. Não tem ``row_version`` nem ``updated_at``: nunca é alterado."""
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_tenant_seq", "tenant_id", "seq"),
                      Index("ix_audit_log_target", "tenant_id", "target_type", "target_id"), {"schema": "audit"})
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(80))
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
