"""Responsabilidade e autoria do laudo (MISSÃO 2, achados A03 R-01/R-02/R-03).

Antes desta regra, o escopo do laudo só conferia a UNIDADE: qualquer médico da mesma unidade conseguia iniciar o
laudo de um exame atribuído a outro, editar o rascunho alheio, enviá-lo para revisão, liberá-lo (assinando em seu
nome) ou registrar adendo. Agora:

* o **médico responsável** é o que iniciou o laudo (``report.report_starts.physician_id``, imutável) ou, antes do
  início, o da atribuição/reserva aberta;
* iniciar o laudo de exame atribuído/reservado a outro médico é recusado (``assigned_to_other``); exame livre pode
  ser iniciado (equivale a assumir: o início registra o próprio médico);
* editar, enviar para revisão, liberar (inclusive em lote), adendo, devolver para correção e enviar ao PACS exigem
  o responsável — exceções explícitas: o revisor designado (segunda leitura) e o compartilhamento temporário com
  escopo ``report`` concedido por quem tem ``ris.exam.share`` (delegação auditada);
* o histórico de revisões do rascunho também é restrito (responsável, revisor, compartilhamento ou quem distribui).

Ocultar botões na interface não é proteção: a verificação é feita no backend.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from vyonix.errors import Conflict, Forbidden

MESSAGE = "Este exame está sob responsabilidade de outro médico."
CODE = "not_responsible"


def _me(s: Session, user_id):
    from vyonix.report.models import Physician
    if user_id is None:
        return None
    return s.execute(select(Physician).where(Physician.user_id == user_id)).scalar_one_or_none()


def responsible(s: Session, study_id: uuid.UUID) -> uuid.UUID | None:
    """Médico responsável: quem iniciou o laudo; antes do início, a atribuição/reserva aberta."""
    from vyonix.report.models import Assignment, ReportStart
    rs = s.execute(select(ReportStart).where(ReportStart.study_id == study_id)).scalar_one_or_none()
    if rs is not None and rs.physician_id is not None:
        return rs.physician_id
    a = s.execute(select(Assignment.physician_id).where(Assignment.study_id == study_id,
                                                        Assignment.status == "open")).first()
    return a[0] if a else None


def check_open(s: Session, study_id: uuid.UUID, user_id) -> None:
    """Iniciar o laudo: exame atribuído/reservado a outro médico é recusado (chamar com a trava do exame)."""
    from vyonix.report.models import Assignment
    a = s.execute(select(Assignment).where(Assignment.study_id == study_id, Assignment.status == "open")
                  ).scalar_one_or_none()
    if a is None:
        return
    me = _me(s, user_id)
    if me is None or me.id != a.physician_id:
        raise Conflict("Este exame está atribuído a outro médico; só ele pode iniciar o laudo.",
                       code="assigned_to_other")


def is_responsible(s: Session, report, user_id, usernames: tuple[str, ...] = ()) -> bool:
    me = _me(s, user_id)
    resp = responsible(s, report.study_id)
    if resp is not None:
        return me is not None and me.id == resp
    # laudo legado sem médico identificado: só o próprio autor registrado
    names = {n.strip().lower()[:120] for n in usernames if n}
    return (report.author or "").strip().lower() in names


def require(s: Session, report, *, user_id, usernames: tuple[str, ...] = (), reviewer: bool = False,
            shared: bool = False, action: str) -> None:
    if reviewer or shared:
        return
    if not is_responsible(s, report, user_id, usernames):
        raise Forbidden(MESSAGE, code=CODE, details={"action": action})
