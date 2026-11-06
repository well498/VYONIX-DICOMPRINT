"""P0 0.3.2 — isolamento por unidade (decisão do proprietário, 05/11/2026).

Regra única, aplicada no backend (rotas, consultas SQL, PACS e visualizadores):

* **R1** objeto com unidade: acessível a quem tem a permissão nessa unidade (ou em todas);
* **R2** objeto **sem unidade** (``site_id NULL``): restrito — só quem tem a permissão em **todas** as unidades
  (até a vinculação correta da unidade, que nunca é feita em massa sem simulação aprovada);
* **R5** listas filtram no SQL, antes do LIMIT; ``NULL`` nunca passa para quem é restrito;
* a instituição continua sendo a fronteira principal (RLS por ``tenant_id``).

Tentativas de acesso direto (por id/UID) fora do escopo geram ``access.denied`` na auditoria (gravado numa sessão
própria pelo tratador de erros, porque a transação da rota é desfeita na recusa).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Iterable

from sqlalchemy import true

from vyonix.errors import Forbidden, NotFound

SENTINEL = uuid.UUID(int=0)          # nunca é unidade real: lista vazia de unidades permitidas → nada passa


def _perms(perms) -> tuple[str, ...]:
    return (perms,) if isinstance(perms, str) else tuple(perms)


def can(p, perms, site_id: uuid.UUID | None) -> bool:
    perms = _perms(perms)
    if site_id is None:
        return any(p.global_has(x) for x in perms)                      # R2
    return any(p.has(x, site_id) for x in perms)                        # R1


def sites(p, perms) -> set | None:
    """``None`` = todas as unidades; senão o conjunto de unidades permitidas (pode ser vazio)."""
    perms = _perms(perms)
    if any(p.global_has(x) for x in perms):
        return None
    out: set = set()
    for x in perms:
        out |= {s for s in (p.grants.get(x) or set()) if s is not None}
    return out if p.stage == "ok" else set()


def where_site(col, allowed: set | None):
    """Condição SQL: ``NULL`` nunca passa quando ``allowed`` não é ``None``."""
    if allowed is None:
        return true()
    return col.in_(list(allowed) or [SENTINEL])


@dataclass
class StudyScope:
    """Escopo de leitura de exames de um usuário.

    ``roles``: unidades permitidas pelos papéis (None = todas); ``physician``: vínculo do médico (queue.scope) quando o
    usuário tem cadastro de médico e não distribui; ``shared``: exames compartilhados explicitamente com ele."""
    roles: set | None
    physician: tuple | None = None
    shared: set = field(default_factory=set)


def study_scope(s, p, perms) -> StudyScope:
    from vyonix.report import queue
    sc = StudyScope(roles=sites(p, perms))
    try:
        sc.physician = queue.scope(s, p.user_id, can_assign=p.has("report.assign"))
    except Exception:                                         # noqa: BLE001 - módulo de laudos ausente
        sc.physician = None
    try:
        from vyonix.ris import prep
        sc.shared = set(prep.shared_studies(s, p.user_id))
    except Exception:                                         # noqa: BLE001 - módulo RIS ausente
        sc.shared = set()
    return sc


def study_ok(sc: StudyScope | None, st) -> bool:
    if sc is None:
        return True
    if getattr(st, "id", None) in sc.shared:
        return True
    site = getattr(st, "site_id", None)
    if sc.physician is not None:
        from vyonix.report import queue
        if queue.allowed(sc.physician, site):
            return True
    if sc.roles is None:
        return True
    return site is not None and site in sc.roles


def deny(c, target_type: str, target_id, perm: str | Iterable[str], reason: str, *, not_found: bool = False):
    """Recusa por escopo: 403 ``site_forbidden`` (ou 404 sem revelar existência) + registro ``access.denied``."""
    perm = _perms(perm)[0] if not isinstance(perm, str) else perm
    if not_found:
        exc = NotFound("Não encontrado.")
    else:
        msg = ("Este exame ainda não tem unidade definida: só quem atua em todas as unidades pode acessá-lo."
               if reason == "no_site" else "Fora das unidades em que você está autorizado.")
        exc = Forbidden(msg, code="site_forbidden", details={"permission": perm})
    raise attach(exc, c, target_type, target_id, perm, reason)


def attach(exc, c, target_type: str, target_id, perm: str, reason: str):
    """Anexa a uma recusa já existente os dados do registro ``access.denied`` (gravado pelo tratador de erros)."""
    exc.audit_denied = {"tenant_id": c.p.tenant_id, "user_id": c.p.user_id, "username": c.p.username, "ip": c.ip,
                        "target_type": target_type, "target_id": str(target_id) if target_id is not None else None,
                        "reason": reason, "permission": perm}
    return exc


class DenyLog:
    """Grava ``access.denied`` com deduplicação (10 min por usuário/alvo/motivo) e teto (20/min por usuário)."""

    def __init__(self, ttl: float = 600.0, per_minute: int = 20) -> None:
        import threading
        self.ttl, self.per_minute = ttl, per_minute
        self._seen: dict[tuple, float] = {}
        self._rate: dict[uuid.UUID, list[float]] = {}
        self._lock = threading.Lock()

    def should_log(self, info: dict) -> bool:
        import time
        now = time.monotonic()
        key = (info["tenant_id"], info["user_id"], info["target_type"], info["target_id"], info["reason"],
               info["permission"])
        with self._lock:
            if len(self._seen) > 10000:
                self._seen = {k: v for k, v in self._seen.items() if now - v < self.ttl}
            if now - self._seen.get(key, -1e9) < self.ttl:
                return False
            hits = [t for t in self._rate.get(info["user_id"], []) if now - t < 60.0]
            if len(hits) >= self.per_minute:
                self._rate[info["user_id"]] = hits
                return False
            hits.append(now)
            self._rate[info["user_id"]] = hits
            self._seen[key] = now
            return True

    def record(self, db, request, info: dict) -> None:
        if not self.should_log(info):
            return
        from vyonix.audit import service as audit
        route = getattr(request.scope.get("route"), "path", None) or request.url.path
        try:
            with db.session(info["tenant_id"]) as s:
                audit.record(s, actor=info["username"], actor_id=info["user_id"], ip=info["ip"],
                             action="access.denied", target_type=info["target_type"], target_id=info["target_id"],
                             details={"reason": info["reason"], "permission": info["permission"], "route": route,
                                      "method": request.method})
        except Exception:                                    # noqa: BLE001 - a recusa vale mesmo sem o registro
            import logging
            logging.getLogger(__name__).exception("Falha ao registrar access.denied")


def user_grants(s, user_id) -> dict[str, set]:
    """Permissões de outro usuário (permissão → {None | unidade}), para validar o destinatário de um compartilhamento."""
    from sqlalchemy import select
    from vyonix.auth.models import Role, RolePermission, User, UserRole
    u = s.get(User, user_id)
    if u is None or not u.active:
        return {}
    out: dict[str, set] = {}
    for site, perm in s.execute(select(UserRole.site_id, RolePermission.permission)
                                .join(Role, Role.id == UserRole.role_id)
                                .join(RolePermission, RolePermission.role_id == Role.id)
                                .where(UserRole.user_id == user_id)).all():
        out.setdefault(perm, set()).add(site)
    return out


def user_can(s, user_id, perms, site_id) -> bool:
    """``can`` para outro usuário: papel na unidade (ou global; sem unidade, só global) ou vínculo de médico."""
    g = user_grants(s, user_id)
    for x in _perms(perms):
        sc = g.get(x) or set()
        if None in sc or (site_id is not None and site_id in sc):
            return True
    try:
        from vyonix.report import queue
        ps = queue.scope(s, user_id, can_assign=False)
        if ps is not None and queue.allowed(ps, site_id):
            return True
    except Exception:                                         # noqa: BLE001
        pass
    return False


def principal_for(s, user_id):
    """Principal sintético (sem sessão) de um usuário, para revalidar credenciais de uso posterior (ex.: Weasis)."""
    from vyonix.auth.models import User
    from vyonix.auth.service import Principal
    u = s.get(User, user_id)
    if u is None or not u.active:
        return None
    return Principal(user_id=u.id, tenant_id=u.tenant_id, username=u.username, display_name=u.display_name,
                     session_id=SENTINEL, csrf="", stage="ok", grants=user_grants(s, user_id))
