"""Distribuição dinâmica dos exames encaminhados aos médicos (Prompt Mestre §12; Central de Exames §7).

Modos (Configurações → REPORT → Distribuição):

* ``manual`` — a coordenação atribui (como antes); o médico também pode **reservar** um exame livre;
* ``fixed`` — todo exame encaminhado vai ao médico fixo da instituição (se tiver vínculo com a unidade);
* ``balanced`` — vai ao médico com vínculo vigente na unidade com **menos exames em aberto** (empate: nome).

Conflitos: o banco garante **uma** atribuição aberta por exame (índice único); duas reservas simultâneas do
mesmo exame — a segunda recebe "já reservado". Reserva **expira** (padrão 60 min) se o médico não começou o
laudo: o exame volta à fila sem perder rascunho (o rascunho, se houver, mantém a reserva). Tudo auditado.
Médicos da rede VYONIX entre instituições: fase própria (exige contrato e acesso entre organizações).
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from vyonix.audit import service as audit
from vyonix.db.base import utcnow
from vyonix.errors import Conflict, Forbidden, NotFound
from vyonix.report.models import Assignment, Physician, Report


def _settings(s: Session) -> dict:
    from vyonix.settings import service as settings
    return settings.get(s, "report", "distribution")


def eligible(s: Session, st) -> list[Physician]:
    from vyonix.report import physicians, queue
    out = []
    for p in s.execute(select(Physician).where(Physician.active.is_(True)).order_by(Physician.full_name)).scalars():
        try:
            physicians.authorized(s, p.user_id, site_id=st.site_id, on=queue._today())
        except Forbidden:
            continue
        out.append(p)
    return out


def _insert(s: Session, fn):
    """Executa a criação da atribuição isolada: violação do índice único vira Conflict (concorrência)."""
    try:
        with s.begin_nested():
            return fn()
    except IntegrityError:
        raise Conflict("Este exame já está atribuído ou reservado por outro médico.", code="already_assigned") from None


def auto_assign(s: Session, st, *, priority: str, actor: str, actor_id=None, ip=None) -> str | None:
    from vyonix.report import queue
    cfg = _settings(s)
    if cfg["mode"] == "manual":
        return None
    if s.execute(select(Assignment).where(Assignment.study_id == st.id, Assignment.status == "open")).first():
        return None                                                     # já atribuído: não duplica
    cands = eligible(s, st)
    target = None
    if cfg["mode"] == "fixed" and cfg.get("physician_id"):
        target = next((p for p in cands if str(p.id) == cfg["physician_id"]), None)
    elif cfg["mode"] == "balanced" and cands:
        load = dict(s.execute(select(Assignment.physician_id, func.count()).where(Assignment.status == "open")
                              .group_by(Assignment.physician_id)).all())
        target = min(cands, key=lambda p: (load.get(p.id, 0), p.full_name))
    if target is None:
        audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="report.distribution.none",
                     target_type="study", target_id=st.id, details={"mode": cfg["mode"]})
        return None
    a = _insert(s, lambda: queue.assign(s, st.id, target.id, priority=priority, actor=f"distribuição:{cfg['mode']}"))
    a.kind = "auto"
    s.flush()
    return target.full_name


def release_expired(s: Session) -> int:
    """Reservas vencidas sem rascunho voltam à fila (auditado)."""
    now = utcnow()
    n = 0
    for a in s.execute(select(Assignment).where(Assignment.status == "open", Assignment.kind == "claimed",
                                                Assignment.reserved_until < now)).scalars():
        if s.execute(select(Report.id).where(Report.study_id == a.study_id)).first():
            continue                                                    # já começou o laudo: mantém
        a.status, a.done_at = "cancelled", now
        n += 1
        audit.record(s, actor="distribuição", action="report.reservation.expired", target_type="study",
                     target_id=a.study_id, details={"physician_id": str(a.physician_id)})
    if n:
        s.flush()
    return n


def claim(s: Session, study_id: uuid.UUID, user_id: uuid.UUID, *, actor: str, ip=None) -> Assignment:
    """O médico reserva um exame encaminhado e livre (com vínculo na unidade)."""
    from vyonix.clinical.models import Study
    from vyonix.report import physicians, queue
    from vyonix.ris.models import ExamPrep
    st = s.get(Study, study_id)
    if st is None:
        raise NotFound("Exame não encontrado.")
    prep = s.execute(select(ExamPrep).where(ExamPrep.study_id == study_id)).scalar_one_or_none()
    if prep is not None and prep.status in ("cancelled", "returned"):
        raise Conflict("Exame cancelado ou devolvido para correção.")
    p = physicians.authorized(s, user_id, site_id=st.site_id, on=queue._today())
    release_expired(s)
    cur = s.execute(select(Assignment).where(Assignment.study_id == study_id, Assignment.status == "open")
                    ).scalar_one_or_none()
    if cur is not None:
        if cur.physician_id == p.id:
            return cur
        raise Conflict("Este exame já está atribuído ou reservado por outro médico.", code="already_assigned")
    minutes = _settings(s)["reservation_minutes"]
    from vyonix.ris import prep as rprep
    pr = rprep.priority_of(s, st, prep)

    def mk():
        a = Assignment(study_id=study_id, physician_id=p.id, priority=pr, status="open", kind="claimed",
                       due_at=utcnow() + timedelta(hours=queue.SLA_HOURS[pr]), assigned_by=actor[:120],
                       reserved_until=utcnow() + timedelta(minutes=minutes))
        s.add(a)
        s.flush()
        return a
    a = _insert(s, mk)
    audit.record(s, actor=actor, actor_id=user_id, ip=ip, action="report.reservation", target_type="study",
                 target_id=study_id, details={"physician_id": str(p.id), "reserved_until": a.reserved_until.isoformat()})
    return a


def release(s: Session, study_id: uuid.UUID, user_id: uuid.UUID, *, actor: str, ip=None) -> None:
    """O médico desiste da reserva (o rascunho, se houver, continua guardado)."""
    p = s.execute(select(Physician).where(Physician.user_id == user_id)).scalar_one_or_none()
    a = s.execute(select(Assignment).where(Assignment.study_id == study_id, Assignment.status == "open")
                  ).scalar_one_or_none()
    if p is None or a is None or a.physician_id != p.id or a.kind != "claimed":
        raise NotFound("Você não tem reserva neste exame.")
    a.status, a.done_at = "cancelled", utcnow()
    s.flush()
    audit.record(s, actor=actor, actor_id=user_id, ip=ip, action="report.reservation.released",
                 target_type="study", target_id=study_id)
