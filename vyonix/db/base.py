"""Base declarativa e colunas comuns.

Toda tabela de negócio tem ``id`` (UUID), ``tenant_id`` (clínica), ``created_at``/``updated_at``
(UTC) e ``row_version`` (controle de concorrência otimista: duas edições simultâneas do mesmo
registro não se sobrescrevem em silêncio). O ``tenant_id`` é preenchido a partir do contexto da
sessão — e o banco confere de novo pela política de row level security.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, MetaData, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

NAMING = {"ix": "ix_%(table_name)s_%(column_0_N_name)s", "uq": "uq_%(table_name)s_%(column_0_N_name)s",
          "ck": "ck_%(table_name)s_%(constraint_name)s", "fk": "fk_%(table_name)s_%(column_0_name)s",
          "pk": "pk_%(table_name)s"}

TENANT_SCHEMAS = ("tenancy", "auth", "clinical", "platform", "audit", "licensing", "pacs")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def _tenant_default(context) -> uuid.UUID:
    from vyonix.db.session import current_tenant
    tid = current_tenant()
    if tid is None:
        raise RuntimeError("Registro sem clínica (tenant) definida no contexto.")
    return tid


class TenantMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True, default=_tenant_default)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(),
                                                 onupdate=utcnow)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    @declared_attr.directive
    def __mapper_args__(cls):  # noqa: N805
        return {"version_id_col": cls.row_version}
