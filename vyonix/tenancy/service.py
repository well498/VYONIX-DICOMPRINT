"""Organizações (clínicas), unidades e instalação inicial."""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from vyonix.audit import service as audit
from vyonix.db.session import Database, tenant_scope
from vyonix.errors import Conflict, NotFound, ValidationFailed
from vyonix.modules import registry
from vyonix.tenancy.models import Organization, Site

CODE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")


def resolve(db: Database, code: str) -> uuid.UUID | None:
    """Organização pelo código (função ``SECURITY DEFINER``: não expõe outras linhas)."""
    with db.session() as s:
        tid = s.execute(text("SELECT tenancy.resolve_organization(:c)"), {"c": code.strip().lower()}).scalar()
    return uuid.UUID(str(tid)) if tid else None


def create_organization(db: Database, *, code: str, name: str, admin_username: str, admin_password: str,
                        admin_name: str = "Administrador", site_name: str = "Unidade principal",
                        document: str | None = None, actor: str = "instalação") -> uuid.UUID:
    from vyonix.auth import service as auth
    code = code.strip().lower()
    if not CODE_RE.match(code):
        raise ValidationFailed("Código da organização: letras minúsculas, números e hífen (2 a 40).")
    if resolve(db, code):
        raise Conflict("Já existe uma organização com esse código.")
    with db.service_session() as s:
        auth.sync_permission_catalog(s)
    tid = uuid.uuid4()
    with db.session(tid) as s:
        s.add(Organization(id=tid, tenant_id=tid, code=code, name=name.strip(), document=document))
        s.flush()
        s.add(Site(name=site_name))
        registry.ensure_rows(s)
        auth.ensure_default_roles(s)
        audit.record(s, actor=actor, action="organization.create", target_type="organization", target_id=tid,
                     details={"code": code})
        auth.create_user(s, username=admin_username, display_name=admin_name, password=admin_password,
                         roles=[("administrador", None)], must_change=False, actor=actor)
    return tid


def refresh(db: Database, tenant_id: uuid.UUID) -> None:
    """Atualiza catálogo, papéis padrão e módulos após atualização de versão."""
    from vyonix.auth import service as auth
    with db.service_session() as s:
        auth.sync_permission_catalog(s)
    with db.session(tenant_id) as s:
        registry.ensure_rows(s)
        auth.ensure_default_roles(s)


def organization(s: Session) -> Organization:
    o = s.execute(select(Organization)).scalar_one_or_none()
    if o is None:
        raise NotFound("Organização não encontrada.")
    return o


def sites(s: Session) -> list[Site]:
    return list(s.execute(select(Site).order_by(Site.name)).scalars())


def save_site(s: Session, *, name: str, site_id: uuid.UUID | None = None, cnes: str | None = None,
              timezone: str | None = None, active: bool | None = None, actor: str, actor_id=None, ip=None) -> Site:
    if site_id:
        site = s.get(Site, site_id)
        if not site:
            raise NotFound("Unidade não encontrada.")
    else:
        site = Site(name=name)
        s.add(site)
    site.name = name.strip() or site.name
    if cnes is not None:
        if cnes and not re.fullmatch(r"\d{7}", cnes):
            raise ValidationFailed("CNES deve ter 7 dígitos.")
        site.cnes = cnes or None
    if timezone:
        from zoneinfo import ZoneInfo
        try:
            ZoneInfo(timezone)
        except Exception:  # noqa: BLE001
            raise ValidationFailed("Fuso horário inválido.") from None
        site.timezone = timezone
    if active is not None:
        site.active = active
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="site.save", target_type="site",
                 target_id=site.id, details={"name": site.name})
    return site


def organizations_for_service(db: Database) -> list[uuid.UUID]:
    with db.service_session() as s:
        return [r for r in s.execute(select(Organization.id).where(Organization.active.is_(True))).scalars()]
