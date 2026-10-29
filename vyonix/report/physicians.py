"""TELELAUDO T1 — cadastro de médicos e vínculos (organização ou unidade, com vigência).

Regra: só libera laudo (e adendo) o usuário que tem cadastro de médico **ativo** com vínculo **vigente** que cubra a
unidade do exame (vínculo com a organização inteira cobre todas as unidades). A identificação do médico (nome,
CRM/UF, RQE) entra na versão liberada e no PDF. O administrador cadastra; não existe liberar "em nome de" outro médico.
"""

from __future__ import annotations

import re
import uuid
from datetime import date
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from vyonix.audit import service as audit
from vyonix.errors import Conflict, Forbidden, NotFound, ValidationFailed
from vyonix.report.models import Physician, PhysicianLink

UFS = ("AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
       "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO")


def identification(p: Physician) -> str:
    """Linha de identificação profissional (rodapé e versão liberada)."""
    if p.footer:
        return p.footer
    out = f"{p.full_name} — CRM {p.crm}/{p.crm_uf}"
    if p.rqe:
        out += f" — RQE {p.rqe}"
    return out


def _out(p: Physician, links: list[PhysicianLink]) -> dict[str, Any]:
    return {"id": str(p.id), "user_id": str(p.user_id), "full_name": p.full_name, "crm": p.crm, "crm_uf": p.crm_uf,
            "rqe": p.rqe, "specialties": p.specialties, "footer": p.footer, "identification": identification(p),
            "active": p.active, "requires_review": p.requires_review,
            "links": [{"id": str(x.id), "site_id": str(x.site_id) if x.site_id else None,
                       "valid_from": x.valid_from.isoformat(), "valid_to": x.valid_to.isoformat() if x.valid_to else None}
                      for x in links]}


def save(s: Session, *, user_id: uuid.UUID, full_name: str, crm: str, crm_uf: str, rqe: str | None = None,
         specialties: list[str] | None = None, footer: str | None = None, active: bool = True,
         requires_review: bool = False, physician_id: uuid.UUID | None = None, actor: str, actor_id=None,
         ip=None) -> Physician:
    from vyonix.auth.models import User
    name = (full_name or "").strip()
    crm_n, uf = re.sub(r"\D", "", crm or ""), (crm_uf or "").strip().upper()
    if len(name) < 5:
        raise ValidationFailed("Informe o nome completo do médico.")
    if not 1 <= len(crm_n) <= 10:
        raise ValidationFailed("CRM: somente números (até 10 dígitos).")
    if uf not in UFS:
        raise ValidationFailed("UF do CRM inválida.")
    rqe_n = ", ".join(x for x in (re.sub(r"\D", "", r) for r in (rqe or "").split(",")) if x)[:40] or None
    if rqe and not rqe_n:
        raise ValidationFailed("RQE: somente números (vários separados por vírgula).")
    if s.get(User, user_id) is None:
        raise NotFound("Usuário não encontrado nesta organização.")
    p = s.get(Physician, physician_id) if physician_id else None
    if physician_id and p is None:
        raise NotFound("Médico não encontrado.")
    for col, val, msg in ((Physician.user_id, user_id, "Esse usuário já tem cadastro de médico."),):
        other = s.execute(select(Physician).where(col == val)).scalar_one_or_none()
        if other is not None and other is not p:
            raise Conflict(msg)
    other = s.execute(select(Physician).where(Physician.crm == crm_n, Physician.crm_uf == uf)).scalar_one_or_none()
    if other is not None and other is not p:
        raise Conflict(f"CRM {crm_n}/{uf} já cadastrado nesta organização.")
    if p is None:
        p = Physician(user_id=user_id, full_name=name, crm=crm_n, crm_uf=uf, specialties=[])
        s.add(p)
    p.user_id, p.full_name, p.crm, p.crm_uf, p.rqe = user_id, name[:160], crm_n, uf, rqe_n
    p.specialties = [x.strip()[:80] for x in (specialties or []) if x and x.strip()][:10]
    p.footer, p.active = ((footer or "").strip()[:200] or None), bool(active)
    p.requires_review = bool(requires_review)
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="report.physician.save", target_type="physician",
                 target_id=p.id, details={"crm": f"{crm_n}/{uf}", "active": p.active,
                                          "requires_review": p.requires_review})
    return p


def add_link(s: Session, physician_id: uuid.UUID, *, site_id: uuid.UUID | None, valid_from: date,
             valid_to: date | None = None, actor: str, actor_id=None, ip=None) -> PhysicianLink:
    from vyonix.tenancy.models import Site
    if s.get(Physician, physician_id) is None:
        raise NotFound("Médico não encontrado.")
    if site_id and s.get(Site, site_id) is None:
        raise NotFound("Unidade não encontrada nesta organização.")
    if valid_to and valid_to < valid_from:
        raise ValidationFailed("Fim da vigência antes do início.")
    link = PhysicianLink(physician_id=physician_id, site_id=site_id, valid_from=valid_from, valid_to=valid_to,
                         created_by=actor[:120])
    s.add(link)
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="report.physician.link", target_type="physician",
                 target_id=physician_id, details={"site_id": str(site_id) if site_id else None,
                                                  "valid_from": valid_from.isoformat(),
                                                  "valid_to": valid_to.isoformat() if valid_to else None})
    return link


def end_link(s: Session, link_id: uuid.UUID, *, valid_to: date, actor: str, actor_id=None, ip=None) -> PhysicianLink:
    link = s.get(PhysicianLink, link_id)
    if link is None:
        raise NotFound("Vínculo não encontrado.")
    if valid_to < link.valid_from:
        raise ValidationFailed("Fim da vigência antes do início.")
    link.valid_to = valid_to
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="report.physician.unlink", target_type="physician",
                 target_id=link.physician_id, details={"link_id": str(link.id), "valid_to": valid_to.isoformat()})
    return link


def listing(s: Session) -> list[dict[str, Any]]:
    out = []
    for p in s.execute(select(Physician).order_by(Physician.full_name)).scalars():
        links = list(s.execute(select(PhysicianLink).where(PhysicianLink.physician_id == p.id)
                               .order_by(PhysicianLink.valid_from)).scalars())
        out.append(_out(p, links))
    return out


def of_user(s: Session, user_id: uuid.UUID) -> dict[str, Any] | None:
    p = s.execute(select(Physician).where(Physician.user_id == user_id)).scalar_one_or_none()
    if p is None:
        return None
    links = list(s.execute(select(PhysicianLink).where(PhysicianLink.physician_id == p.id)).scalars())
    return _out(p, links)


def authorized(s: Session, user_id: uuid.UUID, *, site_id: uuid.UUID | None, on: date) -> Physician:
    """Médico ativo do usuário com vínculo vigente que cubra a unidade do exame; senão recusa a liberação."""
    p = s.execute(select(Physician).where(Physician.user_id == user_id)).scalar_one_or_none()
    if p is None or not p.active:
        raise Forbidden("Somente médico cadastrado e ativo nesta organização pode liberar laudos.",
                        code="physician_required")
    q = select(PhysicianLink).where(PhysicianLink.physician_id == p.id, PhysicianLink.valid_from <= on,
                                    or_(PhysicianLink.valid_to.is_(None), PhysicianLink.valid_to >= on))
    q = q.where(PhysicianLink.site_id.is_(None)) if site_id is None else \
        q.where(or_(PhysicianLink.site_id.is_(None), PhysicianLink.site_id == site_id))
    if s.execute(q.limit(1)).first() is None:
        raise Forbidden("Médico sem vínculo vigente com a unidade deste exame.", code="physician_not_linked")
    return p
