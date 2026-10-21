"""Autenticação, sessões, MFA (TOTP) e usuários.

- Senhas com scrypt; bloqueio após N erros (política ``core.security``), mensagem única para
  usuário inexistente, senha errada ou conta bloqueada/inativa.
- Token de sessão = ``<tenant>.<aleatório 256 bits>``; no banco fica só o SHA-256. A parte do
  tenant permite aplicar o row level security já na consulta da sessão. Expiração deslizante.
- Cada sessão tem um token anti-CSRF próprio (cabeçalho ``X-CSRF-Token`` nas requisições que
  alteram dados).
- MFA TOTP (RFC 6238) com segredo cifrado (AES-GCM, chave local guardada em ``vyonix.secrets``),
  bloqueio de reuso do mesmo código e 10 códigos de recuperação de uso único.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from vyonix.audit import service as audit
from vyonix.auth import passwords, totp
from vyonix.auth.models import AuthSession, MfaFactor, Permission, Role, RolePermission, User, UserRole
from vyonix.db.base import utcnow
from vyonix.errors import Conflict, Forbidden, NotFound, Unauthorized, ValidationFailed
from vyonix.events.bus import publish
from vyonix.modules.manifest import DEFAULT_ROLES, all_permissions
from vyonix.settings import service as settings

GENERIC = "Usuário ou senha inválidos."


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def tenant_of_token(token: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(token.split(".", 1)[0])
    except (ValueError, AttributeError):
        return None


@dataclass
class Principal:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    username: str
    display_name: str
    session_id: uuid.UUID
    csrf: str
    stage: str                                   # ok | password_change | mfa_enroll | mfa_verify
    grants: dict[str, set] = field(default_factory=dict)      # permissão -> {None | site_id}
    roles: list[dict] = field(default_factory=list)

    def has(self, perm: str, site_id: uuid.UUID | None = None) -> bool:
        if self.stage != "ok":
            return False
        scopes = self.grants.get(perm)
        if not scopes:
            return False
        if site_id is None:
            return True               # consulta sem unidade: basta ter a permissão em alguma unidade
        return None in scopes or site_id in scopes

    def global_has(self, perm: str) -> bool:
        return self.stage == "ok" and None in self.grants.get(perm, set())

    def sites_for(self, perm: str) -> set | None:
        """``None`` = todas as unidades; conjunto = só essas."""
        scopes = self.grants.get(perm, set())
        return None if None in scopes else set(scopes)

    def public(self) -> dict:
        return {"user_id": str(self.user_id), "tenant_id": str(self.tenant_id), "username": self.username,
                "display_name": self.display_name, "stage": self.stage, "permissions": sorted(self.grants),
                "roles": self.roles}


# --------------------------------------------------------------------------- catálogo e papéis

def sync_permission_catalog(service_session: Session) -> None:
    """Grava o catálogo global de permissões (só o papel de serviço pode escrever nele)."""
    have = {p.code: p for p in service_session.execute(select(Permission)).scalars()}
    for code, (module, desc) in all_permissions().items():
        if code in have:
            have[code].module, have[code].description = module, desc
        else:
            service_session.add(Permission(code=code, module=module, description=desc))
    service_session.flush()


def _expand(patterns: list[str]) -> list[str]:
    allp = all_permissions()
    out = set()
    for p in patterns:
        if p == "*":
            out |= set(allp)
        elif p.endswith(".*"):
            out |= {c for c in allp if c.startswith(p[:-1])}
        elif p in allp:
            out.add(p)
    return sorted(out)


def ensure_default_roles(s: Session) -> dict[str, Role]:
    roles = {r.code: r for r in s.execute(select(Role)).scalars()}
    for code, (name, patterns) in DEFAULT_ROLES.items():
        r = roles.get(code)
        if r is None:
            r = Role(code=code, name=name, module="core", system=True)
            s.add(r)
            s.flush()
            roles[code] = r
        if r.system:
            want = set(_expand(patterns))
            have = {rp.permission: rp for rp in s.execute(select(RolePermission)
                                                           .where(RolePermission.role_id == r.id)).scalars()}
            for p in want - set(have):
                s.add(RolePermission(role_id=r.id, permission=p))
            for p in set(have) - want:
                s.delete(have[p])
    s.flush()
    return roles


def role_list(s: Session) -> list[dict]:
    perms: dict[uuid.UUID, list[str]] = {}
    for rp in s.execute(select(RolePermission)).scalars():
        perms.setdefault(rp.role_id, []).append(rp.permission)
    return [{"id": str(r.id), "code": r.code, "name": r.name, "system": r.system,
             "permissions": sorted(perms.get(r.id, []))}
            for r in s.execute(select(Role).order_by(Role.name)).scalars()]


def save_role(s: Session, *, code: str, name: str, permissions: list[str], actor: str, actor_id=None,
              ip=None) -> Role:
    allp = all_permissions()
    bad = [p for p in permissions if p not in allp]
    if bad:
        raise ValidationFailed("Permissões desconhecidas.", details={"permissions": bad})
    r = s.execute(select(Role).where(Role.code == code)).scalar_one_or_none()
    if r and r.system:
        raise ValidationFailed("Papéis padrão não podem ser alterados; crie um papel novo.")
    if r is None:
        r = Role(code=code, name=name, module="core", system=False)
        s.add(r)
        s.flush()
    r.name = name
    have = {rp.permission: rp for rp in s.execute(select(RolePermission).where(RolePermission.role_id == r.id))
            .scalars()}
    for p in set(permissions) - set(have):
        s.add(RolePermission(role_id=r.id, permission=p))
    for p in set(have) - set(permissions):
        s.delete(have[p])
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="role.save", target_type="role", target_id=code,
                 details={"permissions": sorted(permissions)})
    s.flush()
    return r


# --------------------------------------------------------------------------- usuários

def _find_user(s: Session, username: str) -> User | None:
    return s.execute(select(User).where(func.lower(User.username) == username.strip().lower())).scalar_one_or_none()


def _policy(s: Session) -> dict:
    return settings.get(s, "core", "security")


def _check_pw(s: Session, password: str) -> None:
    passwords.validate_password(password)
    if len(password) < _policy(s)["password_min_length"]:
        raise ValidationFailed(f"A senha deve ter ao menos {_policy(s)['password_min_length']} caracteres.")


def create_user(s: Session, *, username: str, display_name: str, password: str, roles: list[tuple[str, uuid.UUID | None]],
                email: str | None = None, must_change: bool = True, mfa_required: bool = False, actor: str,
                actor_id=None, ip=None) -> User:
    username = username.strip()
    if not username or len(username) > 60 or any(c.isspace() for c in username):
        raise ValidationFailed("Nome de usuário inválido (sem espaços, até 60 caracteres).")
    if _find_user(s, username):
        raise Conflict("Já existe um usuário com esse nome.")
    _check_pw(s, password)
    u = User(username=username, display_name=display_name.strip() or username, email=email,
             pw_hash=passwords.hash_password(password), must_change=must_change, mfa_required=mfa_required)
    s.add(u)
    s.flush()
    set_roles(s, u.id, roles, actor=actor, actor_id=actor_id, ip=ip, audit_it=False)
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="user.create", target_type="user",
                 target_id=u.id, details={"username": username, "roles": [r for r, _ in roles]})
    publish(s, "core.user.created.v1", {"user_id": str(u.id), "username": username}, source="core",
            subject_kind="user", subject_id=u.id)
    return u


def set_roles(s: Session, user_id: uuid.UUID, roles: list[tuple[str, uuid.UUID | None]], *, actor: str,
              actor_id=None, ip=None, audit_it: bool = True) -> None:
    by_code = {r.code: r for r in s.execute(select(Role)).scalars()}
    unknown = [c for c, _ in roles if c not in by_code]
    if unknown:
        raise ValidationFailed("Papéis desconhecidos.", details={"roles": unknown})
    for ur in s.execute(select(UserRole).where(UserRole.user_id == user_id)).scalars():
        s.delete(ur)
    s.flush()
    for code, site in dict.fromkeys(roles):
        s.add(UserRole(user_id=user_id, role_id=by_code[code].id, site_id=site))
    s.flush()
    _guard_last_admin(s)
    if audit_it:
        audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="user.roles", target_type="user",
                     target_id=user_id, details={"roles": [{"role": c, "site_id": str(x) if x else None}
                                                           for c, x in roles]})


def _guard_last_admin(s: Session) -> None:
    n = s.execute(select(func.count()).select_from(UserRole).join(Role, Role.id == UserRole.role_id)
                  .join(User, User.id == UserRole.user_id)
                  .where(Role.code == "administrador", UserRole.site_id.is_(None), User.active.is_(True))).scalar()
    if not n:
        raise Conflict("A clínica precisa de ao menos um administrador ativo (válido para todas as unidades).")


def update_user(s: Session, user_id: uuid.UUID, *, actor: str, actor_id=None, ip=None, **fields) -> User:
    u = s.get(User, user_id)
    if not u:
        raise NotFound("Usuário não encontrado.")
    allowed = {"display_name", "email", "active", "mfa_required"}
    changed = {}
    for k, v in fields.items():
        if k in allowed and v is not None and getattr(u, k) != v:
            setattr(u, k, v)
            changed[k] = v
    if "active" in changed:
        s.flush()
        _guard_last_admin(s)
        if not u.active:
            _end_sessions(s, u.id)
    if changed:
        audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="user.update", target_type="user",
                     target_id=u.id, details=changed)
    return u


def reset_password(s: Session, user_id: uuid.UUID, new_password: str, *, actor: str, actor_id=None, ip=None) -> None:
    u = s.get(User, user_id)
    if not u:
        raise NotFound("Usuário não encontrado.")
    _check_pw(s, new_password)
    u.pw_hash, u.must_change, u.failed, u.locked_until = passwords.hash_password(new_password), True, 0, None
    _end_sessions(s, u.id)
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="user.password_reset", target_type="user",
                 target_id=u.id)


def unlock(s: Session, user_id: uuid.UUID, *, actor: str, actor_id=None, ip=None) -> None:
    u = s.get(User, user_id)
    if not u:
        raise NotFound("Usuário não encontrado.")
    u.failed, u.locked_until = 0, None
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="user.unlock", target_type="user", target_id=u.id)


def user_list(s: Session) -> list[dict]:
    roles = {r.id: r.code for r in s.execute(select(Role)).scalars()}
    by_user: dict[uuid.UUID, list[dict]] = {}
    for ur in s.execute(select(UserRole)).scalars():
        by_user.setdefault(ur.user_id, []).append({"role": roles.get(ur.role_id),
                                                   "site_id": str(ur.site_id) if ur.site_id else None})
    mfa = {f.user_id for f in s.execute(select(MfaFactor).where(MfaFactor.confirmed_at.is_not(None))).scalars()}
    now = utcnow()
    return [{"id": str(u.id), "username": u.username, "display_name": u.display_name, "email": u.email,
             "active": u.active, "locked": bool(u.locked_until and u.locked_until > now),
             "must_change": u.must_change, "mfa_required": u.mfa_required, "mfa_enabled": u.id in mfa,
             "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
             "roles": by_user.get(u.id, []), "row_version": u.row_version}
            for u in s.execute(select(User).order_by(User.username)).scalars()]


# --------------------------------------------------------------------------- sessões

def _end_sessions(s: Session, user_id: uuid.UUID, except_id: uuid.UUID | None = None) -> None:
    q = select(AuthSession).where(AuthSession.user_id == user_id, AuthSession.ended_at.is_(None))
    for ses in s.execute(q).scalars():
        if ses.id != except_id:
            ses.ended_at = utcnow()


def _mfa_factor(s: Session, user_id: uuid.UUID) -> MfaFactor | None:
    return s.execute(select(MfaFactor).where(MfaFactor.user_id == user_id, MfaFactor.kind == "totp")).scalar_one_or_none()


def _needs_mfa(s: Session, u: User) -> bool:
    if u.mfa_required:
        return True
    if _policy(s)["mfa_required_for_admins"]:
        n = s.execute(select(func.count()).select_from(UserRole).join(Role, Role.id == UserRole.role_id)
                      .where(UserRole.user_id == u.id, Role.code == "administrador")).scalar()
        return bool(n)
    return False


def _stage(s: Session, u: User, ses: AuthSession) -> str:
    if u.must_change:
        return "password_change"
    f = _mfa_factor(s, u.id)
    if f and f.confirmed_at:
        return "ok" if ses.mfa_verified else "mfa_verify"
    if _needs_mfa(s, u):
        return "mfa_enroll"
    return "ok"


def login(s: Session, username: str, password: str, *, ip: str | None = None, user_agent: str | None = None
          ) -> tuple[str, AuthSession, User]:
    """Confere credenciais. Em falha, grava a tentativa e levanta ``Unauthorized`` — o chamador deve
    confirmar a transação mesmo assim (``login_attempt``)."""
    pol = _policy(s)
    u = _find_user(s, username)
    now = utcnow()
    if u is None:
        passwords.check_password(password, passwords.DUMMY_HASH)       # mesmo custo de tempo
        audit.record(s, actor=username[:120] or "?", action="auth.login_failed", details={"reason": "unknown"}, ip=ip)
        raise Unauthorized(GENERIC)
    if not u.active or (u.locked_until and u.locked_until > now):
        passwords.check_password(password, passwords.DUMMY_HASH)
        audit.record(s, actor=u.username, actor_id=u.id, action="auth.login_failed", ip=ip,
                     details={"reason": "inactive" if not u.active else "locked"})
        raise Unauthorized(GENERIC)
    if not passwords.check_password(password, u.pw_hash):
        u.failed += 1
        details = {"reason": "password", "failed": u.failed}
        if u.failed >= pol["lockout_attempts"]:
            u.locked_until, u.failed = now + timedelta(minutes=pol["lockout_minutes"]), 0
            details["locked_until"] = u.locked_until.isoformat()
        audit.record(s, actor=u.username, actor_id=u.id, action="auth.login_failed", details=details, ip=ip)
        raise Unauthorized(GENERIC)
    u.failed, u.locked_until, u.last_login_at = 0, None, now
    raw = f"{u.tenant_id}.{secrets.token_urlsafe(32)}"
    ses = AuthSession(token_hash=token_hash(raw), user_id=u.id, ip=ip, user_agent=(user_agent or "")[:200],
                      expires_at=now + timedelta(minutes=pol["session_minutes"]), mfa_verified=False,
                      csrf=secrets.token_urlsafe(24))
    s.add(ses)
    s.flush()
    audit.record(s, actor=u.username, actor_id=u.id, action="auth.login", target_type="session", target_id=ses.id,
                 ip=ip)
    return raw, ses, u


def authenticate(s: Session, token: str, *, touch: bool = True) -> Principal:
    ses = s.execute(select(AuthSession).where(AuthSession.token_hash == token_hash(token))).scalar_one_or_none()
    now = utcnow()
    if ses is None or ses.ended_at is not None or ses.expires_at <= now:
        raise Unauthorized("Sessão expirada. Entre novamente.")
    u = s.get(User, ses.user_id)
    if u is None or not u.active:
        raise Unauthorized("Sessão encerrada.")
    pol = _policy(s)
    new_exp = now + timedelta(minutes=pol["session_minutes"])
    if touch and (new_exp - ses.expires_at).total_seconds() > 60:
        ses.expires_at = new_exp
    grants: dict[str, set] = {}
    roles = []
    rows = s.execute(select(Role.code, Role.name, UserRole.site_id, RolePermission.permission)
                     .join(UserRole, UserRole.role_id == Role.id)
                     .outerjoin(RolePermission, RolePermission.role_id == Role.id)
                     .where(UserRole.user_id == u.id)).all()
    seen = set()
    for code, name, site, perm in rows:
        if (code, site) not in seen:
            seen.add((code, site))
            roles.append({"role": code, "name": name, "site_id": str(site) if site else None})
        if perm:
            grants.setdefault(perm, set()).add(site)
    return Principal(user_id=u.id, tenant_id=u.tenant_id, username=u.username, display_name=u.display_name,
                     session_id=ses.id, csrf=ses.csrf, stage=_stage(s, u, ses), grants=grants, roles=roles)


def logout(s: Session, p: Principal, ip: str | None = None) -> None:
    ses = s.get(AuthSession, p.session_id)
    if ses and ses.ended_at is None:
        ses.ended_at = utcnow()
        audit.record(s, actor=p.username, actor_id=p.user_id, action="auth.logout", target_type="session",
                     target_id=ses.id, ip=ip)


def change_password(s: Session, p: Principal, current: str, new: str, ip: str | None = None) -> None:
    u = s.get(User, p.user_id)
    if not passwords.check_password(current, u.pw_hash):
        audit.record(s, actor=u.username, actor_id=u.id, action="auth.password_change_failed", ip=ip)
        raise Unauthorized("Senha atual incorreta.")
    if hmac.compare_digest(current, new):
        raise ValidationFailed("A nova senha deve ser diferente da atual.")
    _check_pw(s, new)
    u.pw_hash, u.must_change = passwords.hash_password(new), False
    _end_sessions(s, u.id, except_id=p.session_id)
    audit.record(s, actor=u.username, actor_id=u.id, action="auth.password_change", target_type="user",
                 target_id=u.id, ip=ip)


# --------------------------------------------------------------------------- MFA

def _aad(f_user: uuid.UUID) -> bytes:
    return b"vyonix-mfa:" + str(f_user).encode()


def mfa_enroll_start(s: Session, p: Principal, key: bytes) -> dict:
    f = _mfa_factor(s, p.user_id)
    if f and f.confirmed_at:
        raise Conflict("O segundo fator já está ativo. Desative antes de cadastrar outro.")
    secret = totp.new_secret()
    blob = totp.seal(key, secret.encode(), _aad(p.user_id))
    if f is None:
        s.add(MfaFactor(user_id=p.user_id, kind="totp", secret_enc=blob, last_step=0, recovery_hashes=[]))
    else:
        f.secret_enc, f.last_step = blob, 0
    s.flush()
    return {"secret": secret, "uri": totp.provisioning_uri(secret, p.username)}


def _recovery_hash(code: str) -> str:
    return hashlib.sha256(code.replace("-", "").lower().encode()).hexdigest()


def mfa_enroll_confirm(s: Session, p: Principal, key: bytes, code: str, ip: str | None = None) -> list[str]:
    f = _mfa_factor(s, p.user_id)
    if f is None or f.confirmed_at:
        raise Conflict("Nenhum cadastro de segundo fator em andamento.")
    secret = totp.unseal(key, f.secret_enc, _aad(p.user_id)).decode()
    step = totp.verify(secret, code, last_step=f.last_step)
    if step is None:
        raise ValidationFailed("Código inválido. Confira o horário do celular e tente de novo.")
    codes = [f"{secrets.token_hex(3)}-{secrets.token_hex(3)}" for _ in range(10)]
    f.last_step, f.confirmed_at, f.recovery_hashes = step, utcnow(), [_recovery_hash(c) for c in codes]
    ses = s.get(AuthSession, p.session_id)
    ses.mfa_verified = True
    audit.record(s, actor=p.username, actor_id=p.user_id, action="auth.mfa_enabled", target_type="user",
                 target_id=p.user_id, ip=ip)
    return codes


def mfa_verify(s: Session, p: Principal, key: bytes, code: str, ip: str | None = None) -> None:
    f = _mfa_factor(s, p.user_id)
    if f is None or not f.confirmed_at:
        raise Conflict("Segundo fator não cadastrado.")
    code = code.strip()
    ok = False
    if len(code) == totp.DIGITS and code.isdigit():
        secret = totp.unseal(key, f.secret_enc, _aad(p.user_id)).decode()
        step = totp.verify(secret, code, last_step=f.last_step)
        if step is not None:
            f.last_step, ok = step, True
    else:
        h = _recovery_hash(code)
        if h in f.recovery_hashes:
            f.recovery_hashes = [x for x in f.recovery_hashes if x != h]
            ok = True
            audit.record(s, actor=p.username, actor_id=p.user_id, action="auth.mfa_recovery_used",
                         details={"remaining": len(f.recovery_hashes)}, ip=ip)
    if not ok:
        u = s.get(User, p.user_id)
        u.failed += 1
        pol = _policy(s)
        if u.failed >= pol["lockout_attempts"]:
            u.locked_until, u.failed = utcnow() + timedelta(minutes=pol["lockout_minutes"]), 0
            _end_sessions(s, u.id)
        audit.record(s, actor=p.username, actor_id=p.user_id, action="auth.mfa_failed", ip=ip)
        raise Unauthorized("Código inválido.")
    s.get(AuthSession, p.session_id).mfa_verified = True
    s.get(User, p.user_id).failed = 0
    audit.record(s, actor=p.username, actor_id=p.user_id, action="auth.mfa_verified", ip=ip)


def mfa_disable(s: Session, user_id: uuid.UUID, *, actor: str, actor_id=None, ip=None) -> None:
    f = _mfa_factor(s, user_id)
    if f is None:
        raise NotFound("Segundo fator não cadastrado.")
    s.delete(f)
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="auth.mfa_disabled", target_type="user",
                 target_id=user_id)


def require(p: Principal, perm: str, site_id: uuid.UUID | None = None) -> None:
    if p.stage != "ok":
        raise Forbidden("Conclua a etapa de acesso pendente.", details={"stage": p.stage})
    if not p.has(perm, site_id):
        raise Forbidden("Sem permissão para esta ação.", details={"permission": perm})
