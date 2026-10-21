"""Administração: usuários, papéis, unidades, configurações, módulos e auditoria."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from vyonix.api.app import Ctx, needs
from vyonix.audit import service as audit
from vyonix.auth import service as auth
from vyonix.licensing.service import count_active_users, count_sites
from vyonix.modules import registry
from vyonix.modules.manifest import MANIFESTS, all_permissions
from vyonix.settings import service as settings
from vyonix.tenancy import service as tenancy

router = APIRouter()


class RoleGrant(BaseModel):
    role: str
    site_id: uuid.UUID | None = None


class UserIn(BaseModel):
    username: str = Field(min_length=1, max_length=60)
    display_name: str = Field(min_length=1, max_length=120)
    email: str | None = Field(None, max_length=200)
    password: str = Field(min_length=1, max_length=256)
    roles: list[RoleGrant] = Field(default_factory=list)
    mfa_required: bool = False


class UserPatch(BaseModel):
    display_name: str | None = Field(None, max_length=120)
    email: str | None = Field(None, max_length=200)
    active: bool | None = None
    mfa_required: bool | None = None


class RolesIn(BaseModel):
    roles: list[RoleGrant]


class PasswordReset(BaseModel):
    password: str = Field(max_length=256)


class RoleIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    permissions: list[str]


class SiteIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    cnes: str | None = Field(None, max_length=10)
    timezone: str | None = Field(None, max_length=64)
    active: bool | None = None


class SettingIn(BaseModel):
    value: dict[str, Any]
    reason: str | None = Field(None, max_length=500)
    row_version: int | None = None
    site_id: uuid.UUID | None = None


class ModuleAction(BaseModel):
    reason: str | None = Field(None, max_length=500)


# ------------------------------------------------------------------- usuários e papéis

@router.get("/users")
def users(c: Ctx = Depends(needs("core.users.read"))):
    with c.session() as s:
        return auth.user_list(s)


@router.post("/users", status_code=201)
def create_user(body: UserIn, c: Ctx = Depends(needs("core.users.manage"))):
    with c.session() as s:
        c.plat.licensing.enforce_limit(s, "core", "users", count_active_users(s) + 1)
        u = auth.create_user(s, username=body.username, display_name=body.display_name, email=body.email,
                             password=body.password, roles=[(r.role, r.site_id) for r in body.roles],
                             mfa_required=body.mfa_required, **c.actor)
        return {"id": str(u.id)}


@router.patch("/users/{user_id}")
def update_user(user_id: uuid.UUID, body: UserPatch, c: Ctx = Depends(needs("core.users.manage"))):
    with c.session() as s:
        from vyonix.auth.models import User
        u = s.get(User, user_id)
        if body.active and u is not None and not u.active:
            c.plat.licensing.enforce_limit(s, "core", "users", count_active_users(s) + 1)
        auth.update_user(s, user_id, **body.model_dump(exclude_unset=True), **c.actor)
    return {"ok": True}


@router.put("/users/{user_id}/roles")
def set_roles(user_id: uuid.UUID, body: RolesIn, c: Ctx = Depends(needs("core.users.manage"))):
    with c.session() as s:
        auth.set_roles(s, user_id, [(r.role, r.site_id) for r in body.roles], **c.actor)
    return {"ok": True}


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: uuid.UUID, body: PasswordReset, c: Ctx = Depends(needs("core.users.manage"))):
    with c.session() as s:
        auth.reset_password(s, user_id, body.password, **c.actor)
    return {"ok": True}


@router.post("/users/{user_id}/unlock")
def unlock(user_id: uuid.UUID, c: Ctx = Depends(needs("core.users.manage"))):
    with c.session() as s:
        auth.unlock(s, user_id, **c.actor)
    return {"ok": True}


@router.delete("/users/{user_id}/mfa")
def mfa_reset(user_id: uuid.UUID, c: Ctx = Depends(needs("core.users.manage"))):
    with c.session() as s:
        auth.mfa_disable(s, user_id, **c.actor)
    return {"ok": True}


@router.get("/roles")
def roles(c: Ctx = Depends(needs("core.users.read"))):
    with c.session() as s:
        return auth.role_list(s)


@router.put("/roles/{code}")
def save_role(code: str, body: RoleIn, c: Ctx = Depends(needs("core.users.manage"))):
    with c.session() as s:
        r = auth.save_role(s, code=code, name=body.name, permissions=body.permissions, **c.actor)
        return {"id": str(r.id)}


@router.get("/permissions")
def permissions(c: Ctx = Depends(needs("core.users.read"))):
    return [{"code": k, "module": m, "description": d} for k, (m, d) in sorted(all_permissions().items())]


# ------------------------------------------------------------------- organização e unidades

def _site(x) -> dict:
    return {"id": str(x.id), "name": x.name, "cnes": x.cnes, "timezone": x.timezone, "active": x.active}


@router.get("/organization")
def organization(c: Ctx = Depends(needs("core.settings.read"))):
    with c.session() as s:
        o = tenancy.organization(s)
        return {"id": str(o.id), "code": o.code, "name": o.name, "document": o.document,
                "sites": [_site(x) for x in tenancy.sites(s)]}


@router.get("/sites")
def sites(c: Ctx = Depends(needs("core.settings.read"))):
    with c.session() as s:
        return [_site(x) for x in tenancy.sites(s)]


@router.post("/sites", status_code=201)
def create_site(body: SiteIn, c: Ctx = Depends(needs("core.sites.manage"))):
    with c.session() as s:
        c.plat.licensing.enforce_limit(s, "core", "sites", count_sites(s) + 1)
        return _site(tenancy.save_site(s, **body.model_dump(), **c.actor))


@router.patch("/sites/{site_id}")
def update_site(site_id: uuid.UUID, body: SiteIn, c: Ctx = Depends(needs("core.sites.manage"))):
    with c.session() as s:
        from vyonix.tenancy.models import Site
        cur = s.get(Site, site_id)
        if body.active and cur is not None and not cur.active:
            c.plat.licensing.enforce_limit(s, "core", "sites", count_sites(s) + 1)
        return _site(tenancy.save_site(s, site_id=site_id, **body.model_dump(), **c.actor))


# ------------------------------------------------------------------- configurações

@router.get("/settings")
def settings_list(c: Ctx = Depends(needs("core.settings.read"))):
    with c.session() as s:
        out = []
        for m in MANIFESTS.values():
            if m.available:
                out += [settings.describe(s, m.code, spec.key) for spec in m.settings]
        return out


@router.get("/settings/{module}/{key}")
def setting_get(module: str, key: str, site_id: uuid.UUID | None = None,
                c: Ctx = Depends(needs("core.settings.read"))):
    with c.session() as s:
        return settings.describe(s, module, key, site_id)


@router.put("/settings/{module}/{key}")
def setting_put(module: str, key: str, body: SettingIn, c: Ctx = Depends(needs("core.settings.manage"))):
    with c.session() as s:
        settings.put(s, module, key, body.value, reason=body.reason, site_id=body.site_id,
                     expected_version=body.row_version, **c.actor)
    with c.session() as s:
        return settings.describe(s, module, key, body.site_id)


@router.get("/settings/{module}/{key}/history")
def setting_history(module: str, key: str, c: Ctx = Depends(needs("core.settings.read"))):
    with c.session() as s:
        return settings.history(s, module, key)


# ------------------------------------------------------------------- módulos

@router.get("/modules")
def modules(c: Ctx = Depends(needs("core.license.read"))):
    with c.session() as s:
        return registry.listing(s, c.plat.licensing.module_ok)


@router.post("/modules/{code}/enable")
def module_enable(code: str, c: Ctx = Depends(needs("core.modules.manage"))):
    with c.session() as s:
        registry.enable(s, code, license_check=c.plat.licensing.module_ok, **c.actor)
    return {"ok": True}


@router.post("/modules/{code}/disable")
def module_disable(code: str, body: ModuleAction, c: Ctx = Depends(needs("core.modules.manage"))):
    with c.session() as s:
        registry.disable(s, code, reason=body.reason or "", **c.actor)
    return {"ok": True}


# ------------------------------------------------------------------- auditoria

@router.get("/audit")
def audit_list(limit: int = 100, before_seq: int | None = None, action: str | None = None,
               target_type: str | None = None, target_id: str | None = None, actor: str | None = None,
               c: Ctx = Depends(needs("core.audit.read"))):
    with c.session() as s:
        rows = audit.query(s, limit=limit, before_seq=before_seq, action=action, target_type=target_type,
                           target_id=target_id, actor=actor)
        return [{"seq": r.seq, "at": r.at.isoformat(), "actor": r.actor, "action": r.action,
                 "target_type": r.target_type, "target_id": r.target_id, "details": r.details, "ip": r.ip,
                 "hash": r.hash} for r in rows]


@router.get("/audit/verify")
def audit_verify(c: Ctx = Depends(needs("core.audit.read"))):
    with c.session() as s:
        bad = audit.verify(s)
    return {"ok": not bad, "broken": bad}
