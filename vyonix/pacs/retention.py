"""Retenção de estudos do PACS: **relatório** dos estudos que já passaram do prazo mínimo de guarda configurado e
marcação de **guarda obrigatória** por estudo (processo judicial, pedido do paciente, pesquisa).

Nada é excluído: a exclusão de imagens de pacientes é irreversível e exige autorização expressa, procedimento
próprio e confirmação jurídica do prazo (não implementada). O prazo padrão (20 anos) é só um ponto de partida e
deve ser confirmado pelo jurídico da clínica.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vyonix.audit import service as audit
from vyonix.errors import NotFound, ValidationFailed
from vyonix.pacs.models import PacsInstance, PacsStudy
from vyonix.settings import service as settings


def _cutoff(today: date, years: int) -> date:
    try:
        return today.replace(year=today.year - years)
    except ValueError:                                       # 29/02
        return today.replace(year=today.year - years, day=28)


def report(s: Session, *, today: date | None = None, limit: int = 200) -> dict[str, Any]:
    """Estudos com data (do estudo; sem ela, a do recebimento) anterior ao prazo — fora os em guarda obrigatória."""
    years = settings.get(s, "pacs", "retention")["years"]
    today = today or date.today()
    cut = _cutoff(today, years)
    ref = func.coalesce(PacsStudy.study_date, func.date(PacsStudy.last_received_at))
    size = (select(PacsInstance.study_id, func.count().label("n"), func.sum(PacsInstance.size_bytes).label("b"))
            .group_by(PacsInstance.study_id).subquery())
    base = select(PacsStudy, size.c.n, size.c.b).outerjoin(size, size.c.study_id == PacsStudy.id).where(ref < cut)
    rows = list(s.execute(base.where(PacsStudy.retention_hold.is_(False)).order_by(ref)))
    held = s.execute(select(func.count()).select_from(PacsStudy)
                     .where(ref < cut, PacsStudy.retention_hold.is_(True))).scalar() or 0
    total_held = s.execute(select(func.count()).select_from(PacsStudy)
                           .where(PacsStudy.retention_hold.is_(True))).scalar() or 0
    return {"years": years, "cutoff": cut.isoformat(), "eligible": len(rows),
            "eligible_bytes": int(sum(b or 0 for _st, _n, b in rows)), "eligible_on_hold": int(held),
            "on_hold": int(total_held), "deletion": "não implementada (exige autorização expressa)",
            "items": [{"study_uid": st.study_uid, "study_date": st.study_date.isoformat() if st.study_date else None,
                       "received": st.last_received_at.date().isoformat(), "accession": st.accession,
                       "description": st.description, "instances": int(n or 0), "bytes": int(b or 0)}
                      for st, n, b in rows[:limit]]}


def set_hold(s: Session, study_uid: str, hold: bool, *, reason: str | None, actor: str, actor_id=None,
             ip=None) -> PacsStudy:
    st = s.execute(select(PacsStudy).where(PacsStudy.study_uid == study_uid)).scalar_one_or_none()
    if st is None:
        raise NotFound("Estudo não encontrado.")
    reason = (reason or "").strip()
    if hold and not reason:
        raise ValidationFailed("Informe o motivo da guarda obrigatória.")
    st.retention_hold, st.retention_hold_reason = bool(hold), (reason[:300] if hold else None)
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="pacs.retention.hold", target_type="pacs_study",
                 target_id=st.id, details={"hold": bool(hold), "reason": reason[:300] if hold else None})
    return st
