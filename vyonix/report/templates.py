"""TELELAUDO T3 — modelos de laudo com versões e campos dinâmicos.

* Modelo = identidade (nome, modalidade, procedimento, unidade, preferencial) + versões. A versão em **rascunho** é
  editável; **publicar** exige a confirmação de que o texto e a pré-visualização foram conferidos, torna a versão
  imutável e arquiva a publicada anterior. Laudos usam sempre a versão publicada e registram qual foi.
* Seções: técnica, achados e conclusão. Campos dinâmicos ``{{campo}}`` só da lista abaixo (validados ao salvar);
  preenchidos com os dados do cadastro/RIS/PACS ao abrir o laudo. Campo sem dado fica ``[não informado]``.
* Modelos antigos (sem versões) continuam utilizáveis: o texto vira a versão 1 publicada no primeiro uso.
* **Texto rico:** a versão pode ser ``text`` (padrão) ou ``html`` (subconjunto seguro de ``richtext``: negrito,
  itálico, sublinhado, listas, tabelas e títulos — p.ex. importado do Word). Campos dinâmicos em HTML são preenchidos
  com o valor **escapado** (um nome com ``<`` não vira marcação).
* **Modelos pessoais:** ``owner_user_id`` preenchido = modelo do próprio médico; só ele vê, usa e edita. Não entram
  na seleção automática (T4), que continua só com os modelos da instituição.
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

MAX_SECTION = 10000          # texto simples
MAX_SECTION_HTML = 100000    # texto rico (marcação conta no tamanho)
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


def render(text: str, ctx: dict[str, str | None], fmt: str = "text") -> str:
    import html as _html
    esc = (lambda x: _html.escape(x, quote=False)) if fmt == "html" else (lambda x: x)
    return _RE.sub(lambda m: esc(ctx.get(m.group(1)) or MISSING) if m.group(1) in FIELDS else m.group(0), text or "")


def fmt_of(v: TemplateVersion | dict | None) -> str:
    if v is None:
        return "text"
    return (v.get("content_format") if isinstance(v, dict) else getattr(v, "content_format", None)) or "text"


def compose(v: TemplateVersion | dict, ctx: dict[str, str | None] | None = None) -> str:
    """Texto inicial do laudo a partir das seções (só as preenchidas), com os campos já preenchidos. Em HTML, cada
    seção vem com o título em negrito e o conteúdo formatado do modelo."""
    import html as _html
    from vyonix.report import richtext
    get = (lambda k: v.get(k, "")) if isinstance(v, dict) else (lambda k: getattr(v, k))
    fmt = fmt_of(v)
    if fmt == "html":
        text = "".join(f"<p><strong>{_html.escape(title)}:</strong></p>{(get(k) or '').strip()}"
                       for k, title in SECTIONS if richtext.to_text(get(k) or "", "html").strip())
    else:
        parts = [f"{title}:\n{(get(k) or '').strip()}" for k, title in SECTIONS if (get(k) or "").strip()]
        text = "\n\n".join(parts)
    return render(text, ctx, fmt) if ctx is not None else text


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


BLOCK_DEFAULT = {"show_image": True, "position": "block", "align": "left", "height_mm": 14, "show_name": True,
                 "show_crm": True, "show_specialty": False, "show_rqe": True}


def block_settings(cfg: dict | None) -> dict[str, Any]:
    """Bloco de assinatura do modelo: imagem sim/não, posição (bloco profissional após o texto ou rodapé da última
    página), alinhamento, altura proporcional (8–30 mm) e linhas de identificação (nome, CRM/UF, especialidade, RQE)."""
    out = dict(BLOCK_DEFAULT)
    for k, v in (cfg or {}).items():
        if k not in BLOCK_DEFAULT:
            raise ValidationFailed(f"Opção desconhecida no bloco de assinatura: {k}.")
        out[k] = v
    if out["position"] not in ("block", "footer") or out["align"] not in ("left", "center", "right"):
        raise ValidationFailed("Posição (bloco ou rodapé) ou alinhamento (esquerda, centro, direita) inválido.")
    try:
        out["height_mm"] = float(out["height_mm"])
    except (TypeError, ValueError):
        raise ValidationFailed("Altura da assinatura inválida.") from None
    if not 8 <= out["height_mm"] <= 30:
        raise ValidationFailed("Altura da imagem da assinatura: 8 a 30 mm.")
    for k in ("show_image", "show_name", "show_crm", "show_specialty", "show_rqe"):
        out[k] = bool(out[k])
    return out


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
         findings: str = "", conclusion: str = "", template_id: uuid.UUID | None = None,
         signature_block: dict | None = None, content_format: str = "text", owner_user_id: uuid.UUID | None = None,
         actor: str, actor_id=None, ip=None) -> tuple[ReportTemplate, TemplateVersion]:
    """Cria ou altera o modelo e grava o rascunho (cria um rascunho novo se a última versão já foi publicada).
    ``owner_user_id``: modelo pessoal desse usuário (só na criação; um modelo não muda de dono)."""
    from vyonix.clinical.models import Procedure
    from vyonix.report import richtext
    from vyonix.tenancy.models import Site
    name = (name or "").strip()
    if not name or len(name) > 120:
        raise ValidationFailed("Nome do modelo: 1 a 120 caracteres.")
    if content_format not in richtext.FORMATS:
        raise ValidationFailed("Formato do modelo inválido.")
    limit = MAX_SECTION_HTML if content_format == "html" else MAX_SECTION
    for txt in (technique, findings, conclusion):
        if len(txt or "") > limit:
            raise ValidationFailed(f"Cada seção do modelo: até {limit} caracteres.")
    if content_format == "html":
        technique, findings, conclusion = (richtext.sanitize(x) for x in (technique, findings, conclusion))
    bad = unknown_fields(technique, findings, conclusion)
    if bad:
        raise ValidationFailed(f"Campos desconhecidos no modelo: {', '.join(bad)}.",
                               details={"unknown_fields": bad, "allowed": sorted(FIELDS)})
    block = block_settings(signature_block) if signature_block is not None else None
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
    if t is not None and t.owner_user_id != owner_user_id:
        raise NotFound("Modelo não encontrado.")                  # pessoal de outro usuário, ou troca de dono
    if owner_user_id is not None and (procedure_id or site_id or preferred):
        procedure_id, site_id, preferred = None, None, False      # pessoal: sem regras de seleção automática
    if t is None:
        t = ReportTemplate(name=name, created_by=actor[:120], body="", owner_user_id=owner_user_id)
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
    v.content_format = content_format
    if block is not None:
        v.signature_block = block
    elif v.signature_block is None and vs:                         # novo rascunho herda o bloco da versão anterior
        v.signature_block = next((x.signature_block for x in reversed(vs) if x.signature_block), None)
    t.body = richtext.to_text(compose(v), content_format)[:MAX_SECTION * 3]   # texto legível do último rascunho
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="report.template.save", target_type="report_template",
                 target_id=t.id, details={"name": t.name, "version": v.version, "status": "draft",
                                          "format": content_format, "personal": owner_user_id is not None})
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
    from vyonix.report import richtext
    if not richtext.to_text(compose(draft), fmt_of(draft)).strip():
        raise ValidationFailed("Modelo vazio não pode ser publicado.")
    for v in vs:
        if v.status == "published":
            v.status = "archived"
    draft.status, draft.published_by, draft.published_at = "published", actor[:120], utcnow()
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="report.template.publish",
                 target_type="report_template", target_id=t.id, details={"version": draft.version})
    return draft


def owned_by(t: ReportTemplate, user_id) -> bool:
    """Modelo visível para o usuário: da instituição ou pessoal dele."""
    return t.owner_user_id is None or (user_id is not None and t.owner_user_id == user_id)


def listing(s: Session, *, modality: str | None = None, include_inactive: bool = False,
            only_published: bool = False, user_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
    """Modelos da instituição e os pessoais de ``user_id`` (os pessoais de outros médicos nunca aparecem)."""
    q = select(ReportTemplate).order_by(ReportTemplate.name)
    if not include_inactive:
        q = q.where(ReportTemplate.active.is_(True))
    out = []
    for t in s.execute(q).scalars():
        if not owned_by(t, user_id):
            continue
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
                    "body": compose(pub) if pub else "", "content_format": fmt_of(pub or last),
                    "personal": t.owner_user_id is not None,
                    "published_version": pub.version if pub else None,
                    "draft": None if last is None or last.status != "draft" else
                    {"version": last.version, "technique": last.technique, "findings": last.findings,
                     "conclusion": last.conclusion, "import_report": last.import_report,
                     "content_format": fmt_of(last),
                     "signature_block": block_settings(last.signature_block)},
                    "signature_block": block_settings((pub or last).signature_block if (pub or last) else None),
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
    cands = [t for t in s.execute(select(ReportTemplate).where(ReportTemplate.active.is_(True),
                                                                ReportTemplate.owner_user_id.is_(None))).scalars()
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
