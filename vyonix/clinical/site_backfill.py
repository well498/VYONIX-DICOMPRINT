"""Unidade dos estudos antigos (P0 0.3.2): simulação somente leitura e aplicação de simulação aprovada.

* ``simulate``: para cada estudo sem unidade, propõe uma unidade com a evidência encontrada; NÃO grava nada (transação
  READ ONLY no papel da aplicação, com RLS da instituição).
* ``apply``: só aceita o arquivo de simulação cujo SHA-256 foi aprovado pelo proprietário; reavalia cada estudo, grava
  apenas onde a unidade continua vazia e a evidência não mudou, e audita cada atribuição.
Nenhum dado de paciente sai no arquivo (sem nome, accession ou UID).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from vyonix.audit import service as audit
from vyonix.audit.models import AuditEntry
from vyonix.clinical.models import Encounter, Order, Study, StudySiteAssignment
from vyonix.db.base import utcnow
from vyonix.db.session import Database
from vyonix.pacs.models import PacsDicomNode, PacsStudy
from vyonix.report.models import ReportStart
from vyonix.ris.models import Schedule
from vyonix.tenancy.models import Organization, Site

FORMAT = "vyonix.unidade-simulacao/1"
STRENGTH = {"pedido": 3, "atendimento": 3, "unica": 3, "agendamento": 2, "no_dicom_ae": 2, "no_dicom_estacao": 1}
CSV_COLS = ("study_id", "study_date", "modality", "status", "decisao", "unidade_proposta_id", "unidade_proposta",
            "evidencias", "conflito", "laudo_iniciado")
MAX_AGE_DAYS = 7


class BackfillRefused(Exception):
    pass


def _canon(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------------------------------------- coleta (só leitura)
class _Ctx:
    """Mapas carregados uma vez por instituição (evita N+1)."""

    def __init__(self, s: Session, tid: uuid.UUID) -> None:
        self.tid = tid
        self.sites = {x.id: x for x in s.execute(select(Site).where(Site.tenant_id == tid)).scalars()}
        self.node_site = {n.ae_title.strip().upper(): n.site_id for n in
                          s.execute(select(PacsDicomNode).where(PacsDicomNode.tenant_id == tid)).scalars()
                          if n.site_id}
        self.started = set(s.execute(select(ReportStart.study_id).where(ReportStart.tenant_id == tid)).scalars())
        self.calling: dict[str, set[str]] = {}         # pacs_study_id -> AEs chamadores (auditoria de C-STORE)
        q = (select(AuditEntry.actor, text("audit.audit_log.details->>'study_id'"))
             .where(AuditEntry.tenant_id == tid, AuditEntry.target_type == "instance",
                    AuditEntry.action == "pacs.instance.store", AuditEntry.actor.like("dicom:%")))
        for actor, psid in s.execute(q.execution_options(yield_per=5000)):
            if psid:
                self.calling.setdefault(psid, set()).add(actor.split(":", 1)[1].strip().upper())

    def site_ok(self, sid) -> bool:
        return sid is not None and sid in self.sites


def _evidence(s: Session, c: _Ctx, st: Study) -> list[dict]:
    ev: list[dict] = []
    o = s.get(Order, st.order_id) if st.order_id else None
    if o is not None:
        if c.site_ok(o.site_id):
            ev.append({"fonte": "pedido", "site_id": str(o.site_id), "ref": str(o.id)})
        if o.encounter_id:
            e = s.get(Encounter, o.encounter_id)
            if e is not None and c.site_ok(e.site_id):
                ev.append({"fonte": "atendimento", "site_id": str(e.site_id), "ref": str(e.id)})
    sch_q = select(Schedule).where(Schedule.tenant_id == c.tid, Schedule.study_instance_uid == st.study_instance_uid)
    if st.order_id:
        sch_q = select(Schedule).where(Schedule.tenant_id == c.tid,
                                       (Schedule.study_instance_uid == st.study_instance_uid)
                                       | (Schedule.order_id == st.order_id))
    for sc in s.execute(sch_q).scalars():
        sid = c.node_site.get((sc.station_aet or "").strip().upper())
        if c.site_ok(sid):
            ev.append({"fonte": "agendamento", "site_id": str(sid), "ref": str(sc.id), "ae": sc.station_aet})
    ps = s.execute(select(PacsStudy).where(PacsStudy.tenant_id == c.tid, PacsStudy.clinical_study_id == st.id)
                   ).scalar_one_or_none()
    if ps is not None:
        for ae in sorted(c.calling.get(str(ps.id), ())):
            sid = c.node_site.get(ae)
            if c.site_ok(sid):
                ev.append({"fonte": "no_dicom_ae", "site_id": str(sid), "ae": ae})
        sid = c.node_site.get((ps.source_ae or "").strip().upper())
        if c.site_ok(sid):
            ev.append({"fonte": "no_dicom_estacao", "site_id": str(sid), "ae": ps.source_ae})
    if len(c.sites) == 1:
        ev.append({"fonte": "unica", "site_id": str(next(iter(c.sites)))})
    return ev


def _classify(c: _Ctx, st: Study, ev: list[dict]) -> dict:
    solid = {e["site_id"] for e in ev if STRENGTH[e["fonte"]] >= 2}
    weak = {e["site_id"] for e in ev if STRENGTH[e["fonte"]] == 1}
    best = max((STRENGTH[e["fonte"]] for e in ev), default=0)
    row = {"study_id": str(st.id), "study_date": st.study_date.isoformat() if st.study_date else None,
           "modality": st.modality, "evidencias": ev, "laudo_iniciado": st.id in c.started,
           "conflito": None, "unidade_proposta_id": None, "unidade_proposta": None}
    if len(solid) > 1 or (not solid and len(weak) > 1):
        row.update(status="conflito", decisao="revisar", conflito=sorted(solid or weak))
        return row
    chosen = next(iter(solid or weak), None)
    if chosen is None:
        row.update(status="sem_proposta", decisao="revisar")
        return row
    site = c.sites[uuid.UUID(chosen)]
    row.update(unidade_proposta_id=chosen, unidade_proposta=site.name)
    if not solid:
        row.update(status="fraca", decisao="revisar")
    elif best >= 3 and site.active and not row["laudo_iniciado"] and not (weak - solid):
        row.update(status="proposta", decisao="aplicar")
    else:
        row.update(status="proposta", decisao="revisar")
    return row


def _org(s: Session) -> Organization:
    o = s.execute(select(Organization)).scalar_one_or_none()         # RLS: só a própria instituição
    if o is None:
        raise BackfillRefused("Instituição não encontrada na sessão (RLS).")
    return o


def simulate(db: Database, tenant_id: uuid.UUID, *, limit: int | None = None) -> dict:
    """Somente leitura: nada é gravado (a transação é READ ONLY; qualquer escrita falha no banco)."""
    with db.session(tenant_id) as s:
        s.execute(text("SET TRANSACTION READ ONLY"))
        org = _org(s)
        c = _Ctx(s, tenant_id)
        q = (select(Study).where(Study.tenant_id == tenant_id, Study.site_id.is_(None))
             .order_by(Study.created_at, Study.id))
        if limit:
            q = q.limit(limit)
        rows = [_classify(c, st, _evidence(s, c, st)) for st in s.execute(q).scalars()]
        total = s.execute(text("SELECT count(*) FROM clinical.studies WHERE tenant_id = :t"),
                          {"t": str(tenant_id)}).scalar()
        org_code = org.code
        units = {str(k): {"nome": v.name, "ativa": v.active} for k, v in c.sites.items()}
        s.rollback()                                    # nada é gravado
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"formato": FORMAT, "org_code": org_code, "tenant_id": str(tenant_id),
            "gerado_em": utcnow().isoformat(), "estudos_total": total, "estudos_sem_unidade": len(rows),
            "contagem": counts, "unidades": units,
            "linhas": rows}


def write_outputs(sim: dict, json_path, csv_path=None) -> str:
    data = json.dumps(sim, ensure_ascii=False, sort_keys=True, indent=1, default=str).encode("utf-8")
    with open(json_path, "xb") as f:                                   # nunca sobrescreve uma simulação
        f.write(data)
    if csv_path:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=CSV_COLS, extrasaction="ignore", delimiter=";")
        w.writeheader()
        for r in sim["linhas"]:
            w.writerow({**r, "evidencias": "; ".join(f'{e["fonte"]}:{e.get("ae") or e.get("ref") or ""}'
                                                     for e in r["evidencias"]),
                        "conflito": ",".join(r["conflito"] or [])})
        with open(csv_path, "x", encoding="utf-8-sig", newline="") as f:
            f.write(buf.getvalue())
    return sha256_bytes(data)


# ---------------------------------------------------------------------------------------------- aplicação
def load_approved(path, expected_sha256: str, *, org_code: str, tenant_id: uuid.UUID,
                  max_age_days: int = MAX_AGE_DAYS) -> tuple[dict, str]:
    with open(path, "rb") as f:
        raw = f.read()
    h = sha256_bytes(raw)
    if h != expected_sha256.strip().lower():
        raise BackfillRefused("O arquivo não é o aprovado (SHA-256 diferente).")
    sim = json.loads(raw)
    if sim.get("formato") != FORMAT:
        raise BackfillRefused("Formato de simulação desconhecido.")
    if sim.get("org_code") != org_code or sim.get("tenant_id") != str(tenant_id):
        raise BackfillRefused("Simulação de outra instituição.")
    gen = datetime.fromisoformat(sim["gerado_em"])
    if utcnow() - gen > timedelta(days=max_age_days):
        raise BackfillRefused(f"Simulação com mais de {max_age_days} dias: simule de novo.")
    return sim, h


def apply(db: Database, tenant_id: uuid.UUID, sim: dict, sim_sha256: str, *, approved_by: str, actor: str,
          dry_run: bool = False) -> dict:
    if not approved_by.strip():
        raise BackfillRefused("Informe quem aprovou a simulação.")
    out = {"aplicados": 0, "pulados": [], "simulacao_sha256": sim_sha256, "seco": dry_run}
    todo = [r for r in sim["linhas"] if r.get("decisao") == "aplicar"]
    for r in todo:
        sid = uuid.UUID(r.get("unidade_escolhida") or r["unidade_proposta_id"])
        with db.session(tenant_id) as s:                               # papel app: RLS da instituição
            s.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                      {"k": f"site-backfill:{tenant_id}"})
            st = s.execute(select(Study).where(Study.id == uuid.UUID(r["study_id"]),
                                               Study.tenant_id == tenant_id).with_for_update()).scalar_one_or_none()
            reason = None
            if st is None:
                reason = "estudo não encontrado"
            elif st.site_id is not None:
                reason = "estudo já tem unidade"
            elif s.get(Site, sid) is None:
                reason = "unidade inexistente nesta instituição"
            else:
                c = _Ctx(s, tenant_id)          # recarrega por estudo (ver nota de desempenho)
                now = _classify(c, st, _evidence(s, c, st))
                if r.get("unidade_escolhida"):                        # escolha manual do proprietário
                    ok = now["status"] != "conflito" or r["unidade_escolhida"] in (now["conflito"] or [])
                else:
                    ok = now["status"] == "proposta" and now["unidade_proposta_id"] == str(sid)
                if not ok or now["evidencias"] != r["evidencias"]:
                    reason = "evidência mudou desde a simulação"
                elif s.execute(select(StudySiteAssignment.id).where(
                        StudySiteAssignment.simulation_sha256 == sim_sha256,
                        StudySiteAssignment.study_id == st.id)).first():
                    reason = "já aplicado por esta simulação"
            if reason:
                out["pulados"].append({"study_id": r["study_id"], "motivo": reason})
                s.rollback()
                continue
            if dry_run:
                out["aplicados"] += 1
                s.rollback()
                continue
            source = "manual" if r.get("unidade_escolhida") else "simulacao"
            st.site_id, st.site_source, st.site_set_at, st.site_set_by = sid, source, utcnow(), actor[:120]
            s.add(StudySiteAssignment(study_id=st.id, from_site_id=None, to_site_id=sid, source=source,
                                      evidence=r["evidencias"], simulation_sha256=sim_sha256,
                                      approved_by=approved_by[:120], actor=actor[:120]))
            s.flush()
            audit.record(s, actor=actor, action="clinical.study.site", target_type="study", target_id=st.id,
                         details={"from": None, "to": str(sid), "source": source, "how": "unidade-aplicar",
                                  "simulation_sha256": sim_sha256, "approved_by": approved_by[:120],
                                  "evidence": [e["fonte"] for e in r["evidencias"]],
                                  "laudo_iniciado": r.get("laudo_iniciado", False)})
            out["aplicados"] += 1
    if not dry_run:
        with db.session(tenant_id) as s:
            audit.record(s, actor=actor, action="clinical.study.site_backfill", target_type="organization",
                         target_id=tenant_id, details={"simulation_sha256": sim_sha256, "approved_by": approved_by,
                                                       "aplicados": out["aplicados"],
                                                       "pulados": len(out["pulados"])})
    return out
