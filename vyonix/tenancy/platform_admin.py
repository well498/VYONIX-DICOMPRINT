"""Administração global VYONIX (Prompt Mestre §4 e §16): a operadora VYONIX cadastra, ativa e desativa
instituições e cria o administrador inicial de cada uma.

Limites deliberados:

* só usuários da organização **operadora** (``kind = operator``) com ``platform.institutions.*`` chegam aqui;
* a operadora vê dados **administrativos** das instituições (cadastro, situação, contagens), nunca dados
  clínicos: pacientes, estudos e laudos continuam isolados pelo RLS — não há acesso automático da VYONIX a eles
  (acesso excepcional a dado clínico exigirá autorização, justificativa, prazo e auditoria; ainda não existe);
* "módulos contratados" é a intenção registrada no cadastro; o direito de uso continua vindo da licença assinada;
* desativar uma instituição bloqueia o acesso dos usuários dela e encerra as sessões, **sem apagar nada**.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from vyonix.audit import service as audit
from vyonix.db.base import utcnow
from vyonix.db.session import Database
from vyonix.errors import Forbidden, NotFound, ValidationFailed
from vyonix.tenancy.models import Organization, Site

TYPES = {"clinica": "Clínica", "hospital": "Hospital", "cdi": "Centro de diagnóstico", "telelaudo": "Telelaudo"}
MODULES = ("pacs", "ris", "report", "print")


def cnpj_ok(doc: str) -> bool:
    d = re.sub(r"\D", "", doc or "")
    if len(d) != 14 or len(set(d)) == 1:
        return False
    def dv(base: str, w: list[int]) -> str:
        r = sum(int(a) * b for a, b in zip(base, w)) % 11
        return "0" if r < 2 else str(11 - r)
    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    return d[12] == dv(d[:12], w1) and d[13] == dv(d[:13], [6] + w1)


def require_operator(s: Session) -> Organization:
    """A sessão precisa ser da operadora VYONIX (instituições não administram outras instituições)."""
    org = s.execute(select(Organization)).scalar_one_or_none()
    if org is None or org.kind != "operator":
        raise Forbidden("Disponível só para a administração VYONIX.", code="operator_only")
    return org


OPERATOR_ROLE = ("admin_vyonix", "Administrador Geral VYONIX",
                 ["platform.*", "core.users.read", "core.users.manage", "core.audit.read", "core.settings.read",
                  "core.settings.manage", "core.license.read"])


def create_operator(db: Database, *, code: str, name: str, admin_username: str, admin_password: str,
                    actor: str = "instalação") -> uuid.UUID:
    """Organização operadora VYONIX. O administrador geral recebe o papel ``admin_vyonix`` (administração global,
    usuários da operadora, auditoria) — **sem** permissões clínicas (pacientes, imagens, laudos)."""
    from vyonix.auth import service as auth
    from vyonix.auth.models import User
    from vyonix.tenancy import service as tenancy
    tid = tenancy.create_organization(db, code=code, name=name, admin_username=admin_username,
                                      admin_password=admin_password, admin_name="Administrador Geral VYONIX",
                                      site_name="VYONIX", actor=actor, register_login=True, kind="operator")
    with db.session(tid) as s:
        rc, rn, perms = OPERATOR_ROLE
        auth.save_role(s, code=rc, name=rn, permissions=auth.expand(perms), actor=actor)
        u = s.execute(select(User)).scalar_one()
        auth.set_roles(s, u.id, [(rc, None)], actor=actor)
    return tid


def _row(o: Organization, users: int, sites: int, modules: list[str]) -> dict[str, Any]:
    return {"id": str(o.id), "code": o.code, "name": o.name, "legal_name": o.legal_name, "document": o.document,
            "institution_type": o.institution_type, "active": o.active, "status_reason": o.status_reason,
            "contact_name": o.contact_name, "contact_email": o.contact_email, "contact_phone": o.contact_phone,
            "contracted_modules": o.contracted_modules or [], "enabled_modules": modules,
            "users": users, "sites": sites, "created_at": o.created_at.isoformat()}


def institutions(db: Database) -> list[dict[str, Any]]:
    """Só dados administrativos e contagens (papel de serviço, sem consultar tabelas clínicas)."""
    from vyonix.auth.models import User
    from vyonix.modules.models import ModuleState
    with db.service_session() as s:
        orgs = list(s.execute(select(Organization).where(Organization.kind == "institution")
                              .order_by(Organization.name)).scalars())
        users = dict(s.execute(select(User.tenant_id, func.count()).where(User.active.is_(True))
                               .group_by(User.tenant_id)).all())
        sites = dict(s.execute(select(Site.tenant_id, func.count()).group_by(Site.tenant_id)).all())
        mods: dict = {}
        for m in s.execute(select(ModuleState).where(ModuleState.status == "enabled",
                                                     ModuleState.code.not_in(("core", "clinical")))).scalars():
            mods.setdefault(m.tenant_id, []).append(m.code)
        return [_row(o, int(users.get(o.id, 0)), int(sites.get(o.id, 0)), sorted(mods.get(o.id, []))) for o in orgs]


def create_institution(db: Database, *, code: str, name: str, institution_type: str, admin_login: str,
                       admin_name: str, admin_password: str, legal_name: str | None = None,
                       document: str | None = None, sites: list[str] | None = None, structure: str = "clinica_pequena",
                       modules: list[str] | None = None, contact_name: str | None = None,
                       contact_email: str | None = None, contact_phone: str | None = None, actor: str,
                       actor_id=None, ip=None, operator_id: uuid.UUID) -> uuid.UUID:
    """Assistente: dados → módulos contratados → estrutura → administrador inicial (senha provisória, troca no
    primeiro acesso). Profissionais são cadastrados depois pelo gestor da instituição."""
    from vyonix.auth import service as auth
    from vyonix.modules.manifest import ROLE_TEMPLATES, STRUCTURES
    from vyonix.tenancy import service as tenancy
    if institution_type not in TYPES:
        raise ValidationFailed(f"Tipo de instituição inválido (use: {', '.join(TYPES)}).")
    if document and not cnpj_ok(document):
        raise ValidationFailed("CNPJ inválido (dígitos verificadores não conferem).")
    if structure not in STRUCTURES and structure != "personalizado":
        raise ValidationFailed("Estrutura inválida.")
    bad = [m for m in (modules or []) if m not in MODULES]
    if bad:
        raise ValidationFailed(f"Módulos desconhecidos: {', '.join(bad)}.")
    names = [x.strip() for x in (sites or []) if x.strip()] or ["Unidade principal"]
    if len(set(n.lower() for n in names)) != len(names) or any(len(n) > 120 for n in names):
        raise ValidationFailed("Nomes de unidades repetidos ou longos demais.")
    doc = re.sub(r"\D", "", document or "") or None
    tid = tenancy.create_organization(
        db, code=code, name=name, admin_username=admin_login, admin_password=admin_password, admin_name=admin_name,
        site_name=names[0], document=doc, actor=f"VYONIX:{actor}", register_login=True, admin_must_change=True,
        institution_type=institution_type, legal_name=(legal_name or "").strip() or None,
        contact_name=contact_name, contact_email=contact_email, contact_phone=contact_phone,
        contracted_modules=sorted(set(modules or [])))
    with db.session(tid) as s:
        for n in names[1:]:
            s.add(Site(name=n))
        for t in STRUCTURES.get(structure, ("", []))[1]:
            if t in ROLE_TEMPLATES:
                auth.activate_template(s, t, actor=f"VYONIX:{actor}")
        audit.record(s, actor=f"VYONIX:{actor}", action="platform.institution.setup", target_type="organization",
                     target_id=tid, details={"structure": structure, "sites": len(names),
                                             "modules": sorted(set(modules or []))})
    with db.session(operator_id) as s:
        audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="platform.institution.create",
                     target_type="organization", target_id=tid,
                     details={"code": code, "type": institution_type, "admin_login": admin_login})
    return tid


def set_active(db: Database, org_id: uuid.UUID, active: bool, *, reason: str | None, actor: str, actor_id=None,
               ip=None, operator_id: uuid.UUID) -> None:
    """Desativar bloqueia o acesso e encerra as sessões; nenhum dado é apagado. Reativar devolve o acesso."""
    from vyonix.auth.models import AuthSession
    reason = (reason or "").strip()
    if not active and not reason:
        raise ValidationFailed("Informe o motivo da desativação.")
    with db.service_session() as s:
        o = s.get(Organization, org_id)
        if o is None or o.kind != "institution":
            raise NotFound("Instituição não encontrada.")
        o.active, o.status_reason = bool(active), (reason[:300] or None)
        if not active:
            s.execute(update(AuthSession).where(AuthSession.tenant_id == org_id, AuthSession.ended_at.is_(None))
                      .values(ended_at=utcnow()))
    with db.session(org_id) as s:
        audit.record(s, actor=f"VYONIX:{actor}", action="platform.institution.active", target_type="organization",
                     target_id=org_id, details={"active": bool(active), "reason": reason[:300] or None})
    with db.session(operator_id) as s:
        audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="platform.institution.active",
                     target_type="organization", target_id=org_id,
                     details={"active": bool(active), "reason": reason[:300] or None})
