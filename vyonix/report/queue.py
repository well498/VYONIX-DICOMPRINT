"""TELELAUDO T7 — fila de laudos: escopo do médico por unidade, atribuição, prioridade e prazo (SLA).

* **Escopo:** quem tem cadastro de médico e não tem ``report.assign`` (coordenação) só vê e abre exames das unidades
  em que tem vínculo vigente (vínculo com a organização inteira = todas). Vale para a lista, para abrir o laudo e
  para o PDF — médico remoto não acessa exame de unidade não autorizada.
* **Atribuição:** a coordenação atribui o exame a um médico com vínculo vigente na unidade do exame; prioridade
  define o prazo padrão (``SLA_HOURS``). Um exame tem no máximo uma atribuição aberta; liberar o laudo a conclui.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from vyonix.audit import service as audit
from vyonix.db.base import utcnow
from vyonix.errors import Conflict, Forbidden, NotFound, ValidationFailed
from vyonix.report.models import Assignment, Physician, PhysicianLink

SLA_HOURS = {"stat": 1, "urgent": 4, "routine": 48}
BRT = timezone(timedelta(hours=-3))


def _today() -> date:
    return utcnow().astimezone(BRT).date()


def scope(s: Session, user_id: uuid.UUID, *, can_assign: bool) -> tuple[bool, set] | None:
    """None = sem restrição (coordenação ou usuário que não é médico). Senão (organização_inteira, {unidades})."""
    if can_assign:
        return None
    p = s.execute(select(Physician).where(Physician.user_id == user_id)).scalar_one_or_none()
    if p is None:
        return None
    on = _today()
    links = s.execute(select(PhysicianLink).where(
        PhysicianLink.physician_id == p.id, PhysicianLink.valid_from <= on,
        or_(PhysicianLink.valid_to.is_(None), PhysicianLink.valid_to >= on))).scalars().all()
    if not p.active:
        return (False, set())
    return (any(x.site_id is None for x in links), {x.site_id for x in links if x.site_id})


def allowed(sc: tuple[bool, set] | None, site_id: uuid.UUID | None) -> bool:
    if sc is None:
        return True
    whole, sites = sc
    return whole or (site_id is not None and site_id in sites)


def require(s: Session, sc, study_id: uuid.UUID) -> None:
    from vyonix.clinical.models import Study
    st = s.get(Study, study_id)
    if st is None or not allowed(sc, st.site_id):
        raise Forbidden("Exame de unidade em que você não tem vínculo vigente.", code="out_of_scope")


def assign(s: Session, study_id: uuid.UUID, physician_id: uuid.UUID, *, priority: str = "routine",
           due_at=None, actor: str, actor_id=None, ip=None) -> Assignment:
    from vyonix.clinical.models import Study
    from vyonix.report import physicians
    if priority not in SLA_HOURS:
        raise ValidationFailed(f"Prioridade inválida (use: {', '.join(SLA_HOURS)}).")
    st = s.get(Study, study_id)
    p = s.get(Physician, physician_id)
    if st is None or p is None:
        raise NotFound("Exame ou médico não encontrado.")
    physicians.authorized(s, p.user_id, site_id=st.site_id, on=_today())      # médico precisa poder laudar ali
    for old in s.execute(select(Assignment).where(Assignment.study_id == study_id,
                                                  Assignment.status == "open")).scalars():
        old.status, old.done_at = "cancelled", utcnow()                         # reatribuição
    s.flush()
    a = Assignment(study_id=study_id, physician_id=physician_id, priority=priority, status="open",
                   due_at=due_at or (utcnow() + timedelta(hours=SLA_HOURS[priority])), assigned_by=actor[:120])
    s.add(a)
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="report.assign", target_type="study",
                 target_id=study_id, details={"physician_id": str(physician_id), "priority": priority,
                                              "due_at": a.due_at.isoformat()})
    return a


def close_for_study(s: Session, study_id: uuid.UUID) -> None:
    for a in s.execute(select(Assignment).where(Assignment.study_id == study_id,
                                                Assignment.status == "open")).scalars():
        a.status, a.done_at = "done", utcnow()


def open_by_study(s: Session) -> dict[uuid.UUID, dict[str, Any]]:
    now = utcnow()
    out = {}
    for a, p in s.execute(select(Assignment, Physician).join(Physician, Physician.id == Assignment.physician_id)
                          .where(Assignment.status == "open")):
        out[a.study_id] = {"assignment_id": str(a.id), "physician_id": str(p.id), "physician": p.full_name,
                           "physician_user_id": str(p.user_id), "priority": a.priority,
                           "due_at": a.due_at.isoformat(), "overdue": a.due_at < now}
    return out
