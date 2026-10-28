from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from vyonix.db.base import Base, TenantMixin


class User(TenantMixin, Base):
    __tablename__ = "users"
    __table_args__ = (Index("uq_users_tenant_username", "tenant_id", text("lower(username)"), unique=True),
                      {"schema": "auth"})
    username: Mapped[str] = mapped_column(String(60), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str | None] = mapped_column(String(200))
    pw_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    must_change: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    mfa_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Role(TenantMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (Index("uq_roles_tenant_code", "tenant_id", "code", unique=True), {"schema": "auth"})
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    module: Mapped[str] = mapped_column(String(30), nullable=False, default="core")
    system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Permission(Base):
    """Catálogo global de permissões (declaradas pelos manifestos dos módulos)."""
    __tablename__ = "permissions"
    __table_args__ = {"schema": "auth"}
    code: Mapped[str] = mapped_column(String(80), primary_key=True)
    module: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)


class RolePermission(TenantMixin, Base):
    __tablename__ = "role_permissions"
    __table_args__ = (Index("uq_role_permissions_role_perm", "role_id", "permission", unique=True),
                      {"schema": "auth"})
    role_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("auth.roles.id", ondelete="CASCADE"), nullable=False)
    permission: Mapped[str] = mapped_column(String(80), ForeignKey("auth.permissions.code"), nullable=False)


class UserRole(TenantMixin, Base):
    """Papel do usuário; ``site_id`` vazio = todas as unidades."""
    __tablename__ = "user_roles"
    __table_args__ = (Index("uq_user_roles_user_role_site", "user_id", "role_id", "site_id", unique=True,
                            postgresql_nulls_not_distinct=True), {"schema": "auth"})
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("auth.roles.id", ondelete="CASCADE"), nullable=False)
    site_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tenancy.sites.id"))


class AuthSession(TenantMixin, Base):
    __tablename__ = "sessions"
    __table_args__ = (Index("uq_sessions_token_hash", "token_hash", unique=True), {"schema": "auth"})
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(200))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    mfa_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    csrf: Mapped[str] = mapped_column(String(64), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MfaFactor(TenantMixin, Base):
    __tablename__ = "mfa_factors"
    __table_args__ = (Index("uq_mfa_factors_user_kind", "user_id", "kind", unique=True), {"schema": "auth"})
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default="totp")
    secret_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)       # anti-reuso do código
    recovery_hashes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    note: Mapped[str | None] = mapped_column(Text)


class LoginDirectory(Base):
    """Diretório **global** de logins (servidor com várias instituições): o identificador de acesso é único na
    plataforma e aponta para a conta institucional dona dele. Não é cadastro compartilhado — senha, papéis e
    dados continuam só na conta da instituição. Sem ``tenant_id`` (consultado antes de existir a organização da
    sessão); só o papel de serviço acessa."""
    __tablename__ = "login_directory"
    __table_args__ = (Index("uq_login_directory_user", "user_id", unique=True), {"schema": "auth"})
    login: Mapped[str] = mapped_column(String(60), primary_key=True)            # minúsculas
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
