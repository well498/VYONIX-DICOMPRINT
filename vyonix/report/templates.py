"""TELELAUDO T3 — modelos de laudo com versões e campos dinâmicos.

* Modelo = identidade (nome, modalidade, procedimento, unidade, preferencial) + versões. A versão em **rascunho** é
  editável; **publicar** exige a confirmação de que o texto e a pré-visualização foram conferidos, torna a versão
  imutável e arquiva a publicada anterior. Laudos usam sempre a versão publicada e registram qual foi.
* Seções: técnica, achados e conclusão. Campos dinâmicos ``{{campo}}`` só da lista abaixo (validados ao salvar);
  preenchidos com os dados do cadastro/RIS/PACS ao abrir o laudo. Campo sem dado fica ``[não informado]``.
* Modelos antigos (sem versões) continuam utilizáveis: o texto vira a versão 1 publicada no primeiro uso.
"""

from __future__ import annotations

import re
import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vyonix.audit import service as audit
from vyonix.db.base import utcnow
from vyonix.errors import Conflict, NotFound, ValidationFailed
from vyonix.report.models import ReportTemplate, TemplateVersion

MAX_SECTION = 10000
FIELDS = {
    "paciente.nome": "Nome do paciente", "paciente.nascimento": "Data de nascimento", "paciente.sexo": "Sexo",
    "paciente.idade": "Idade", "exame.modalidade": "Modalidade", "exame.descricao": "Descrição do exame",
    "exame.data": "Data do exame", "exame.accession": "Número de acesso", "exame.solicitante": "Médico solicitante",
    "instituicao.nome": "Nome da instituição", "unidade.nome": "Unidade",
}
_RE = re.compile(r"\{\{\s*([a-z_.]+)\s*\}\}")
MISSING = "[não informado]"
SECTIONS = (("technique", "Técnica"), ("findings", "Achados"), ("conclusion", "Conclusão"))


def unknown_fields(*texts: str) -> list[str]:
    return sorted({m for t in texts for m in _RE.findall(t or "") if m not in FIELDS})


def render(text: str, ctx: dict[str, str | None]) -> str:
    return _RE.sub(lambda m: (ctx.get(m.group(1)) or MISSING) if m.group(1) in FIELDS else m.group(0), text or "")


def compose(v: TemplateVersion | dict, ctx: dict[str, str | None] | None = None) -> str:
    """Texto inicial do laudo a partir das seções (só as preenchidas), com os campos já preenchidos."""
    get = (lambda k: v.get(k, "")) if isinstance(v, dict) else (lambda k: getattr(v, k))
    parts = [f"{title}:\n{(get(k) or '').strip()}" for k, title in SECTIONS if (get(k) or "").strip()]
    text = "\n\n".join(parts)
    return render(text, ctx) if ctx is not None else text


def context(s: Session, study_id: uuid.UUID) -> dict[str, str | None]:
    """Campos administrativos validados do cadastro clínico (paciente, pedido, estudo, unidade, instituição)."""
    from vyonix.clinical.models import Order, Patient, Study
    from vyonix.settings import service as settings
    from vyonix.tenancy.models import Site
    st = s.get(Study, study_id)
    p = s.get(Patient, st.patient_id) if st and st.patient_id else None
    o = s.get(Order, st.order_id) if st and st.order_id else None
    site = s.get(Site, st.site_id) if st and st.site_id else None
    age = None
    if p and p.birth_date and st and st.study_date:
        b, d = p.birth_date, st.study_date
        age = f"{d.year - b.year - ((d.month, d.day) < (b.month, b.day))} anos"
    return {"paciente.nome": p.name if p else None,
            "paciente.nascimento": p.birth_date.strftime("%d/%m/%Y") if p and p.birth_date else None,
            "paciente.sexo": {"F": "Feminino", "M": "Masculino", "O": "Outro"}.get(p.sex or "") if p else None,
            "paciente.idade": age, "exame.modalidade": st.modality if st else None,
            "exame.descricao": st.description if st else None,
            "exame.data": st.study_date.strftime("%d/%m/%Y") if st and st.study_date else None,
            "exame.accession": st.accession if st else None, "exame.solicitante": o.requester if o else None,
            "instituicao.nome": settings.get(s, "core", "institution").get("display_name") or None,
            "unidade.nome": site.name if site else None}


def _versions(s: Session, tid: uuid.UUID) -> list[TemplateVersion]:
    return list(s.execute(select(TemplateVersion).where(TemplateVersion.template_id == tid)
                          .order_by(TemplateVersion.version)).scalars())


def published(s: Session, t: ReportTemplate) -> TemplateVersion | None:
    vs = _versions(s, t.id)
    if not vs and (t.body or "").strip():                     # modelo anterior às versões: vira a versão 1 publicada
        v = TemplateVersion(template_id=t.id, version=1, status="published", technique="", findings=t.body,
                            conclusion="", created_by=t.created_by, published_by=t.created_by, published_at=utcnow())
        s.add(v)
        s.flush()
        return v
    return next((v for v in reversed(vs) if v.status == "published"), None)


def save(s: Session, *, name: str, modality: str | None = None, procedure_id: uuid.UUID | None = None,
         site_id: uuid.UUID | None = None, preferred: bool = False, active: bool = True, technique: str = "",
         findings: str = "", conclusion: str = "", template_id: uuid.UUID | None = None, actor: str, actor_id=None,
         ip=None) -> tuple[ReportTemplate, TemplateVersion]:
    """Cria ou altera o modelo e grava o rascunho (cria um rascunho novo se a última versão já foi publicada)."""
    from vyonix.clinical.models import Procedure
    from vyonix.tenancy.models import Site
    name = (name or "").strip()
    if not name or len(name) > 120:
        raise ValidationFailed("Nome do modelo: 1 a 120 caracteres.")
    for txt in (technique, findings, conclusion):
        if len(txt or "") > MAX_SECTION:
            raise ValidationFailed(f"Cada seção do modelo: até {MAX_SECTION} caracteres.")
    bad = unknown_fields(technique, findings, conclusion)
    if bad:
        raise ValidationFailed(f"Campos desconhecidos no modelo: {', '.join(bad)}.",
                               details={"unknown_fields": bad, "allowed": sorted(FIELDS)})
    if procedure_id and s.get(Procedure, procedure_id) is None:
        raise NotFound("Procedimento não encontrado nesta organização.")
    if site_id and s.get(Site, site_id) is None:
        raise NotFound("Unidade não encontrada nesta organização.")
    t = s.get(ReportTemplate, template_id) if template_id else None
    if template_id and t is None:
        raise NotFound("Modelo não encontrado.")
    dup = s.execute(select(ReportTemplate).where(func.lower(ReportTemplate.name) == name.lower())).scalar_one_or_none()
    if dup is not None and dup is not t:
        raise Conflict("Já existe um modelo com esse nome.")
    if t is None:
        t = ReportTemplate(name=name, created_by=actor[:120], body="")
        s.add(t)
    published(s, t) if t.id else None                             # converte modelo antigo antes de versionar
    t.name, t.active, t.preferred = name, bool(active), bool(preferred)
    t.modality = (modality or "").strip().upper()[:16] or None
    t.procedure_id, t.site_id = procedure_id, site_id
    s.flush()
    vs = _versions(s, t.id)
    v = vs[-1] if vs and vs[-1].status == "draft" else None
    if v is None:
        v = TemplateVersion(template_id=t.id, version=(vs[-1].version + 1) if vs else 1, status="draft",
                            created_by=actor[:120])
        s.add(v)
    v.technique, v.findings, v.conclusion = technique or "", findings or "", conclusion or ""
    t.body = compose(v)                                           # texto legível do rascunho mais recente
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="report.template.save", target_type="report_template",
                 target_id=t.id, details={"name": t.name, "version": v.version, "status": "draft"})
    return t, v


def publish(s: Session, template_id: uuid.UUID, *, reviewed: bool, actor: str, actor_id=None,
            ip=None) -> TemplateVersion:
    if not reviewed:
        raise ValidationFailed("Confirme que o texto e a pré-visualização foram conferidos antes de publicar.")
    t = s.get(ReportTemplate, template_id)
    if t is None:
        raise NotFound("Modelo não encontrado.")
    vs = _versions(s, t.id)
    draft = vs[-1] if vs and vs[-1].status == "draft" else None
    if draft is None:
        raise Conflict("Não há rascunho para publicar.")
    if not compose(draft).strip():
        raise ValidationFailed("Modelo vazio não pode ser publicado.")
    for v in vs:
        if v.status == "published":
            v.status = "archived"
    draft.status, draft.published_by, draft.published_at = "published", actor[:120], utcnow()
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="report.template.publish",
                 target_type="report_template", target_id=t.id, details={"version": draft.version})
    return draft


def listing(s: Session, *, modality: str | None = None, include_inactive: bool = False,
            only_published: bool = False) -> list[dict[str, Any]]:
    q = select(ReportTemplate).order_by(ReportTemplate.name)
    if not include_inactive:
        q = q.where(ReportTemplate.active.is_(True))
    out = []
    for t in s.execute(q).scalars():
        if modality and t.modality and t.modality != modality.upper():
            continue
        pub = published(s, t)
        if only_published and pub is None:
            continue
        vs = _versions(s, t.id)
        last = vs[-1] if vs else None
        out.append({"id": str(t.id), "name": t.name, "modality": t.modality, "active": t.active,
                    "procedure_id": str(t.procedure_id) if t.procedure_id else None,
                    "site_id": str(t.site_id) if t.site_id else None, "preferred": t.preferred,
                    "body": compose(pub) if pub else "",
                    "published_version": pub.version if pub else None,
                    "draft": None if last is None or last.status != "draft" else
                    {"version": last.version, "technique": last.technique, "findings": last.findings,
                     "conclusion": last.conclusion},
                    "versions": [{"version": v.version, "status": v.status, "created_by": v.created_by,
                                  "published_by": v.published_by,
                                  "published_at": v.published_at.isoformat() if v.published_at else None}
                                 for v in vs]})
    return out


def sample_context() -> dict[str, str]:
    """Dados fictícios para a pré-visualização (sem dados de pacientes)."""
    return {"paciente.nome": "PACIENTE DE EXEMPLO", "paciente.nascimento": "01/01/1970", "paciente.sexo": "—",
            "paciente.idade": "56 anos", "exame.modalidade": "XX", "exame.descricao": "Exame de exemplo",
            "exame.data": date.today().strftime("%d/%m/%Y"), "exame.accession": "EXEMPLO",
            "exame.solicitante": "Dr(a). Solicitante", "instituicao.nome": "Instituição", "unidade.nome": "Unidade"}


# ------------------------------------------------------------------ seleção automática (T4)
LEVELS = ("unidade + procedimento", "unidade + modalidade", "organização + procedimento",
          "organização + modalidade", "genérico da organização")
BLANK = "Técnica:\n\n\nAchados:\n\n\nConclusão:\n"


def select_for(s: Session, study_id: uuid.UUID) -> dict[str, Any]:
    """Modelo publicado mais específico para o exame, só da organização do exame (RLS + filtro).

    Ordem: unidade+procedimento → unidade+modalidade → organização+procedimento → organização+modalidade →
    genérico da organização → rascunho em branco estruturado. Empate no mesmo nível: o marcado como preferencial;
    sem um único preferencial, a escolha é recusada (``ambiguous``) para o administrador decidir.
    """
    from vyonix.clinical.models import Order, Study
    st = s.get(Study, study_id)
    if st is None:
        raise NotFound("Estudo não encontrado.")
    o = s.get(Order, st.order_id) if st.order_id else None
    proc, mod, site = (o.procedure_id if o else None), (st.modality or "").upper() or None, st.site_id
    cands = [t for t in s.execute(select(ReportTemplate).where(ReportTemplate.active.is_(True))).scalars()
             if published(s, t) is not None]

    def match(t: ReportTemplate, level: int) -> bool:
        if level == 0:
            return bool(site and proc) and t.site_id == site and t.procedure_id == proc
        if level == 1:
            return bool(site and mod) and t.site_id == site and t.procedure_id is None and t.modality == mod
        if level == 2:
            return bool(proc) and t.site_id is None and t.procedure_id == proc
        if level == 3:
            return bool(mod) and t.site_id is None and t.procedure_id is None and t.modality == mod
        return t.site_id is None and t.procedure_id is None and t.modality is None

    for level, name in enumerate(LEVELS):
        found = [t for t in cands if match(t, level)]
        if not found:
            continue
        if len(found) > 1:
            pref = [t for t in found if t.preferred]
            if len(pref) != 1:
                return {"status": "ambiguous", "level": name,
                        "candidates": [{"id": str(t.id), "name": t.name} for t in found],
                        "message": f"Mais de um modelo no nível “{name}” sem um único preferencial: defina o "
                                   "preferencial ou escolha o modelo."}
            found = pref
        t = found[0]
        return {"status": "selected", "level": name, "template_id": str(t.id), "name": t.name,
                "version": published(s, t).version}
    return {"status": "none", "level": None, "message": "Nenhum modelo publicado para este exame: rascunho em branco."}
