"""Laudos: modelos, rascunho, liberação com versão imutável, adendos e verificação de integridade.

A confirmação de identidade (senha) no ato da liberação é feita pela API antes de chamar ``finalize``/``addendum``;
este serviço registra quem liberou e grava o SHA-256 do conteúdo canônico de cada versão.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vyonix.audit import service as audit
from vyonix.clinical.models import Order, Patient, Study
from vyonix.db.base import utcnow
from vyonix.errors import Conflict, NotFound, ValidationFailed
from vyonix.events.bus import publish
from vyonix.report.models import Report, ReportTemplate, ReportVersion

MAX_BODY = 20000


# ------------------------------------------------------------------ modelos
def save_template(s: Session, *, name: str, body: str, modality: str | None = None, active: bool = True,
                  template_id: uuid.UUID | None = None, actor: str, actor_id=None, ip=None) -> ReportTemplate:
    name = (name or "").strip()
    if not name or len(name) > 120:
        raise ValidationFailed("Nome do modelo: 1 a 120 caracteres.")
    if len(body or "") > MAX_BODY:
        raise ValidationFailed(f"Texto do modelo: até {MAX_BODY} caracteres.")
    t = s.get(ReportTemplate, template_id) if template_id else None
    if template_id and t is None:
        raise NotFound("Modelo não encontrado.")
    if t is None:
        if s.execute(select(ReportTemplate).where(func.lower(ReportTemplate.name) == name.lower())).first():
            raise Conflict("Já existe um modelo com esse nome.")
        t = ReportTemplate(name=name, created_by=actor[:120], body="")
        s.add(t)
    t.name, t.body, t.active = name, body or "", bool(active)
    t.modality = (modality or "").strip().upper()[:16] or None
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="report.template.save", target_type="report_template",
                 target_id=t.id, details={"name": t.name, "modality": t.modality, "active": t.active})
    return t


def templates(s: Session, *, modality: str | None = None, include_inactive: bool = False) -> list[dict]:
    q = select(ReportTemplate).order_by(ReportTemplate.name)
    if not include_inactive:
        q = q.where(ReportTemplate.active.is_(True))
    out = []
    for t in s.execute(q).scalars():
        if modality and t.modality and t.modality != modality.upper():
            continue
        out.append({"id": str(t.id), "name": t.name, "modality": t.modality, "body": t.body, "active": t.active})
    return out


# ------------------------------------------------------------------ laudos
def _out(r: Report, s: Session, *, versions: bool = False) -> dict[str, Any]:
    st = s.get(Study, r.study_id)
    d = {"id": str(r.id), "study_id": str(r.study_id), "study_instance_uid": st.study_instance_uid if st else None,
         "order_id": str(r.order_id) if r.order_id else None, "status": r.status, "body": r.body,
         "critical": r.critical, "critical_note": r.critical_note, "author": r.author, "version": r.version,
         "finalized_by": r.finalized_by, "finalized_at": r.finalized_at.isoformat() if r.finalized_at else None,
         "row_version": r.row_version, "updated_at": r.updated_at.isoformat() if r.updated_at else None}
    if versions:
        d["versions"] = [{"version": v.version, "kind": v.kind, "body": v.body, "critical": v.critical,
                          "signed_by": v.signed_by, "signed_at": v.signed_at.isoformat(), "sha256": v.sha256}
                         for v in s.execute(select(ReportVersion).where(ReportVersion.report_id == r.id)
                                            .order_by(ReportVersion.version)).scalars()]
    return d


def open_report(s: Session, study_id: uuid.UUID, *, template_id: uuid.UUID | None = None, actor: str, actor_id=None,
                ip=None) -> Report:
    """Abre o laudo do estudo (cria o rascunho, opcionalmente a partir de um modelo); se já existe, devolve-o."""
    st = s.get(Study, study_id)
    if st is None:
        raise NotFound("Estudo não encontrado.")
    r = s.execute(select(Report).where(Report.study_id == study_id)).scalar_one_or_none()
    if r is not None:
        return r
    body = ""
    if template_id:
        t = s.get(ReportTemplate, template_id)
        if t is None or not t.active:
            raise NotFound("Modelo não encontrado.")
        body = t.body
    r = Report(study_id=st.id, order_id=st.order_id, status="draft", body=body, critical=False, author=actor[:120],
               version=0)
    s.add(r)
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="report.open", target_type="report", target_id=r.id,
                 details={"study_id": str(st.id), "template_id": str(template_id) if template_id else None})
    return r


def update_draft(s: Session, report_id: uuid.UUID, *, body: str, critical: bool = False,
                 critical_note: str | None = None, expected_version: int | None = None, actor: str, actor_id=None,
                 ip=None) -> Report:
    r = s.get(Report, report_id)
    if r is None:
        raise NotFound("Laudo não encontrado.")
    if r.status != "draft":
        raise Conflict("Laudo liberado não pode ser editado; registre um adendo.")
    if expected_version is not None and r.row_version != expected_version:
        raise Conflict("O laudo foi alterado por outra pessoa. Recarregue antes de salvar.")
    if len(body or "") > MAX_BODY:
        raise ValidationFailed(f"Texto do laudo: até {MAX_BODY} caracteres.")
    r.body, r.critical = body or "", bool(critical)
    r.critical_note = ((critical_note or "").strip()[:300] or None) if critical else None
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="report.draft.save", target_type="report",
                 target_id=r.id, details={"chars": len(r.body), "critical": r.critical})
    return r


def _ts(dt) -> str:
    from datetime import timezone
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def canonical(study_uid: str | None, version: int, kind: str, body: str, critical: bool, signer: str, at: str) -> bytes:
    return json.dumps({"study_instance_uid": study_uid, "version": version, "kind": kind, "body": body,
                       "critical": critical, "signed_by": signer, "signed_at": at},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _new_version(s: Session, r: Report, *, kind: str, body: str, critical: bool, actor: str, actor_id) -> ReportVersion:
    st = s.get(Study, r.study_id)
    now = utcnow()
    n = r.version + 1
    v = ReportVersion(report_id=r.id, version=n, kind=kind, body=body, critical=critical, signed_by=actor[:120],
                      signed_by_id=actor_id, signed_at=now,
                      sha256=hashlib.sha256(canonical(st.study_instance_uid if st else None, n, kind, body, critical,
                                                      actor[:120], _ts(now))).hexdigest())
    s.add(v)
    r.version = n
    return v


def finalize(s: Session, report_id: uuid.UUID, *, expected_version: int | None = None, actor: str, actor_id=None,
             ip=None) -> Report:
    """Libera o laudo (a API já confirmou a senha de quem libera)."""
    r = s.get(Report, report_id)
    if r is None:
        raise NotFound("Laudo não encontrado.")
    if r.status != "draft":
        raise Conflict("Laudo já liberado.")
    if expected_version is not None and r.row_version != expected_version:
        raise Conflict("O laudo foi alterado por outra pessoa. Recarregue antes de liberar.")
    if not (r.body or "").strip():
        raise ValidationFailed("Laudo vazio não pode ser liberado.")
    if r.critical and not r.critical_note:
        raise ValidationFailed("Descreva o achado crítico antes de liberar.")
    v = _new_version(s, r, kind="final", body=r.body, critical=r.critical, actor=actor, actor_id=actor_id)
    r.status, r.finalized_by, r.finalized_at = "final", actor[:120], v.signed_at
    s.flush()
    if r.order_id:                                   # laudo liberado conclui o pedido (pelo serviço do cadastro)
        from vyonix.clinical import service as clinical
        o = s.get(Order, r.order_id)
        if o is not None and o.status not in ("completed", "cancelled"):
            clinical.set_order_status(s, o.id, "completed", actor=actor, actor_id=actor_id, ip=ip)
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="report.finalize", target_type="report",
                 target_id=r.id, details={"version": v.version, "sha256": v.sha256, "critical": r.critical})
    publish(s, "report.finalized.v1", {"report_id": str(r.id), "study_id": str(r.study_id), "version": v.version},
            source="report", subject_kind="report", subject_id=r.id)
    if r.critical:
        publish(s, "report.critical.v1", {"report_id": str(r.id), "study_id": str(r.study_id),
                                          "order_id": str(r.order_id) if r.order_id else None},
                source="report", subject_kind="report", subject_id=r.id)
    return r


def addendum(s: Session, report_id: uuid.UUID, text: str, *, critical: bool = False, actor: str, actor_id=None,
             ip=None) -> ReportVersion:
    """Adendo a um laudo liberado (o texto original não muda); a API já confirmou a senha."""
    r = s.get(Report, report_id)
    if r is None:
        raise NotFound("Laudo não encontrado.")
    if r.status != "final":
        raise Conflict("Adendo só em laudo liberado; edite o rascunho.")
    text = (text or "").strip()
    if not text or len(text) > MAX_BODY:
        raise ValidationFailed(f"Texto do adendo: 1 a {MAX_BODY} caracteres.")
    v = _new_version(s, r, kind="addendum", body=text, critical=bool(critical), actor=actor, actor_id=actor_id)
    if critical:
        r.critical = True
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="report.addendum", target_type="report",
                 target_id=r.id, details={"version": v.version, "sha256": v.sha256, "critical": bool(critical)})
    publish(s, "report.amended.v1", {"report_id": str(r.id), "study_id": str(r.study_id), "version": v.version},
            source="report", subject_kind="report", subject_id=r.id)
    if critical:
        publish(s, "report.critical.v1", {"report_id": str(r.id), "study_id": str(r.study_id),
                                          "order_id": str(r.order_id) if r.order_id else None},
                source="report", subject_kind="report", subject_id=r.id)
    return v


def get(s: Session, report_id: uuid.UUID) -> dict[str, Any]:
    r = s.get(Report, report_id)
    if r is None:
        raise NotFound("Laudo não encontrado.")
    return _out(r, s, versions=True)


def verify(s: Session, report_id: uuid.UUID) -> dict[str, Any]:
    """Recalcula o SHA-256 de cada versão liberada (detecta alteração direta no banco)."""
    r = s.get(Report, report_id)
    if r is None:
        raise NotFound("Laudo não encontrado.")
    st = s.get(Study, r.study_id)
    bad = []
    vs = list(s.execute(select(ReportVersion).where(ReportVersion.report_id == r.id)
                        .order_by(ReportVersion.version)).scalars())
    for v in vs:
        h = hashlib.sha256(canonical(st.study_instance_uid if st else None, v.version, v.kind, v.body, v.critical,
                                     v.signed_by, _ts(v.signed_at))).hexdigest()
        if h != v.sha256:
            bad.append(v.version)
    seq_ok = [v.version for v in vs] == list(range(1, len(vs) + 1)) and r.version == len(vs)
    return {"versions": len(vs), "altered": bad, "sequence_ok": seq_ok, "valid": not bad and seq_ok}


def worklist(s: Session, *, status: str | None = None, modality: str | None = None, date_from: date | None = None,
             date_to: date | None = None, limit: int = 200) -> list[dict[str, Any]]:
    """Estudos do cadastro clínico com a situação do laudo: pending (sem laudo), draft, final."""
    q = (select(Study, Patient, Report).outerjoin(Patient, Patient.id == Study.patient_id)
         .outerjoin(Report, Report.study_id == Study.id))
    if status == "pending":
        q = q.where(Report.id.is_(None))
    elif status in ("draft", "final"):
        q = q.where(Report.status == status)
    if modality:
        q = q.where(Study.modality == modality.strip().upper())
    if date_from:
        q = q.where(Study.study_date >= date_from)
    if date_to:
        q = q.where(Study.study_date <= date_to)
    rows = s.execute(q.order_by(Study.study_date.desc().nullslast(), Study.created_at.desc()).limit(min(limit, 500)))
    out = []
    for st, p, r in rows:
        out.append({"study_id": str(st.id), "study_instance_uid": st.study_instance_uid, "accession": st.accession,
                    "modality": st.modality, "study_date": st.study_date.isoformat() if st.study_date else None,
                    "description": st.description, "patient_name": p.name if p else None,
                    "report_id": str(r.id) if r else None, "report_status": r.status if r else "pending",
                    "critical": bool(r.critical) if r else False})
    return out
