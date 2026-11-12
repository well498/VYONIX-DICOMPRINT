"""Painel do Técnico em Radiologia (Prompt Mestre §10): o dia de trabalho numa tela — exames agendados e sua
situação (inclusive o que a modalidade informou pelo MPPS), estudos recebidos pelo PACS, recusas na recepção DICOM
("falhas de transmissão", com o motivo técnico, sem dados do paciente) e pendências de qualidade e conciliação.

Somente leitura e só da própria organização. O técnico não emite nem libera laudos (sem ``report.sign``).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

BRT = timezone(timedelta(hours=-3))


def panel(s: Session, *, day: date | None = None, with_images: bool = True, sites: set | None = None) -> dict[str, Any]:
    from vyonix.audit.models import AuditEntry
    from vyonix.ris import service as ris
    day = day or datetime.now(BRT).date()
    start, end = datetime.combine(day, time.min, tzinfo=BRT), datetime.combine(day, time.max, tzinfo=BRT)
    exams = ris.worklist(s, date_from=day, date_to=day, include_done=True, sites=sites)
    by = {}
    for e in exams:
        by[e["status"]] = by.get(e["status"], 0) + 1
    out: dict[str, Any] = {
        "day": day.isoformat(),
        "exams": [{k: e[k] for k in ("schedule_id", "status", "patient_name", "patient_id", "modality", "station_aet",
                                     "room", "description", "scheduled_at", "accession", "mpps_status", "images",
                                     "study_instance_uid")} for e in exams],
        "exam_counts": by,
        "incomplete_transfers": sum(1 for e in exams if e["images"] and e["images"]["received"] < e["images"]["expected"]),
    }
    # P0 0.3.2: recusas DICOM não têm unidade (revelam AE e origem) — só para quem atua em todas as unidades
    rejects = [] if sites is not None else list(s.execute(select(AuditEntry).where(
        AuditEntry.action == "pacs.instance.reject", AuditEntry.at >= start, AuditEntry.at <= end)
        .order_by(AuditEntry.seq.desc()).limit(50)).scalars())
    out["reception_failures"] = [{"at": r.at.isoformat(), "reason": (r.details or {}).get("reason"),
                                  "via": (r.details or {}).get("via"), "source": r.actor} for r in rejects]
    if with_images:
        from vyonix.pacs import service as pacs
        from vyonix.pacs.models import PacsInstance, PacsStudy
        from vyonix.auth.scope import where_site
        from vyonix.clinical.models import Study
        q = select(PacsStudy, func.count(PacsInstance.id)).outerjoin(
            PacsInstance, PacsInstance.study_id == PacsStudy.id).where(
            PacsStudy.last_received_at >= start, PacsStudy.last_received_at <= end)
        if sites is not None:                    # P0 0.3.2: só estudos ligados a um exame das unidades do usuário
            q = q.join(Study, Study.id == PacsStudy.clinical_study_id).where(where_site(Study.site_id, sites))
        rows = s.execute(q.group_by(PacsStudy.id)
            .order_by(PacsStudy.last_received_at.desc()).limit(100)).all()
        out["received"] = [{"study_uid": st.study_uid, "patient_name": st.patient_name, "accession": st.accession,
                            "description": st.description, "instances": int(n),
                            "received_at": st.last_received_at.isoformat()} for st, n in rows]
        vis = None
        if sites is not None:                    # N10: unidade no SQL antes do limite
            vis = lambda col: col.in_(select(Study.study_instance_uid)            # noqa: E731
                                      .where(where_site(Study.site_id, sites)))
        out["quality_issues"] = pacs.quality_overview(s, limit=100, only_issues=True, visible=vis)
    return out
