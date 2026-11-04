"""Bloqueio de troca de médico e de prioridade a partir do início efetivo da elaboração do laudo.

Regra do proprietário (04/11/2026):

* antes do início do laudo, troca de médico e prioridade seguem as permissões existentes;
* o início é registrado de forma persistente (``report.report_starts``) quando o médico abre o laudo para
  elaborar (cria o rascunho); abrir as imagens no visualizador **não** inicia o bloqueio;
* a partir daí, ambas as alterações ficam bloqueadas em todos os perfis e APIs (inclusive pedidos e operações em
  lote), para rascunho, revisão e laudo assinado; o bloqueio não sai com mudança de status nem com o fechamento do
  editor (o aplicativo não tem UPDATE/DELETE na tabela);
* sem exceção automática para urgência (procedimento excepcional ainda será definido e aprovado);
* operações simultâneas são serializadas por exame (trava de transação no PostgreSQL), de modo que um pedido de
  troca e o início do laudo não passam ao mesmo tempo.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from vyonix.db.base import utcnow
from vyonix.errors import Conflict

MESSAGE = "Alteração indisponível: laudo já iniciado"
CODE = "report_started"


def serialize(s: Session, study_id: uuid.UUID) -> None:
    """Trava por exame até o fim da transação (pedidos concorrentes esperam e então enxergam o início gravado)."""
    if s.get_bind().dialect.name == "postgresql":
        s.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"report-start:{study_id}"})


def started(s: Session, study_id: uuid.UUID) -> dict[str, Any] | None:
    """Início do laudo do exame (ou ``None``). Laudo existente sem registro também conta (defesa em profundidade)."""
    from vyonix.report.models import Report, ReportStart
    r = s.execute(select(ReportStart).where(ReportStart.study_id == study_id)).scalar_one_or_none()
    if r is not None:
        return {"started_at": r.started_at.isoformat(), "started_by": r.started_by,
                "physician": r.physician_name or r.started_by, "report_id": str(r.report_id) if r.report_id else None}
    rep = s.execute(select(Report).where(Report.study_id == study_id)).scalar_one_or_none()
    if rep is not None:
        return {"started_at": rep.created_at.isoformat(), "started_by": rep.author, "physician": rep.author,
                "report_id": str(rep.id)}
    return None


def started_map(s: Session, study_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    from vyonix.report.models import Report, ReportStart
    out: dict[uuid.UUID, dict[str, Any]] = {}
    if not study_ids:
        return out
    for rep in s.execute(select(Report).where(Report.study_id.in_(study_ids))).scalars():
        out[rep.study_id] = {"started_at": rep.created_at.isoformat(), "started_by": rep.author,
                             "physician": rep.author, "report_id": str(rep.id)}
    for r in s.execute(select(ReportStart).where(ReportStart.study_id.in_(study_ids))).scalars():
        out[r.study_id] = {"started_at": r.started_at.isoformat(), "started_by": r.started_by,
                           "physician": r.physician_name or r.started_by,
                           "report_id": str(r.report_id) if r.report_id else None}
    return out


def ensure_unlocked(s: Session, study_id: uuid.UUID, *, action: str) -> None:
    """Recusa troca de médico / prioridade se o laudo já foi iniciado. Chame antes de qualquer alteração."""
    serialize(s, study_id)
    info = started(s, study_id)
    if info is not None:
        raise Conflict(MESSAGE, code=CODE, details={"action": action, **info})


def mark_started(s: Session, study_id: uuid.UUID, report_id: uuid.UUID | None, *, actor: str, actor_id=None,
                 ip=None) -> None:
    """Grava o início (idempotente). Deve rodar na mesma transação que cria o rascunho."""
    from vyonix.audit import service as audit
    from vyonix.report.models import Assignment, Physician, ReportStart
    if s.execute(select(ReportStart.id).where(ReportStart.study_id == study_id)).first():
        return
    a = s.execute(select(Assignment).where(Assignment.study_id == study_id, Assignment.status == "open")
                  ).scalar_one_or_none()
    phys = s.get(Physician, a.physician_id) if a is not None else None
    if phys is None and actor_id is not None:
        phys = s.execute(select(Physician).where(Physician.user_id == actor_id)).scalar_one_or_none()
    rs = ReportStart(study_id=study_id, report_id=report_id, started_at=utcnow(), started_by=actor[:120],
                     started_by_id=actor_id, physician_id=phys.id if phys else None,
                     physician_name=phys.full_name if phys else None, priority=a.priority if a else None,
                     origin="editor")
    s.add(rs)
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="report.started", target_type="study",
                 target_id=study_id, details={"report_id": str(report_id) if report_id else None,
                                              "physician": rs.physician_name, "priority": rs.priority,
                                              "locks": ["trocar_medico", "prioridade"]})
