"""Central de Exames — preparação técnica do estudo antes do laudo.

Fluxo: o estudo chega ao PACS (recebido) → o técnico confere (em preparação), anexa documentos, fotos e áudio,
comenta, registra suspeitas técnicas (com pendência) → encaminha à fila de laudos (encaminhado; com médico
atribuído: "encaminhado ao médico") → o médico pode devolver para correção (devolvido) → laudo liberado. Cancelar
exige permissão e justificativa. Nada é apagado: o estudo DICOM original não muda e todo passo fica na auditoria.

Regras no servidor:

* encaminhar exige as **verificações fixas** (imagens recebidas, recepção encerrada, paciente identificado,
  sem suspeita técnica aberta, duplicidade tratada) — não configuráveis — e os itens **obrigatórios** do checklist
  da instituição (Configurações → RIS → Preparação), que podem variar por modalidade;
* "possível duplicidade" é indício (mesmo paciente, modalidade e data, ou mesmo número de acesso); a decisão é de
  uma pessoa e fica registrada;
* anexos são validados pelo conteúdo, cifrados (AES-GCM, dado associado = organização + estudo) e só saem por rota
  autenticada; áudio é registro do técnico, **nunca** vira texto clínico automaticamente (sem transcrição/IA).
"""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from vyonix.audit import service as audit
from vyonix.clinical.models import Order, Patient, PatientIdentifier, Study
from vyonix.db.base import utcnow
from vyonix.errors import Conflict, Forbidden, NotFound, ValidationFailed
from vyonix.ris.models import ExamAttachment, ExamComment, ExamCommentRead, ExamFlag, ExamPrep, ExamShare

KEY_NAME = "ris_attachment_key"
STAGES = {"received": "Recebido", "preparing": "Em preparação", "pending": "Com pendência",
          "forwarded": "Pronto para laudo", "assigned": "Encaminhado ao médico", "returned": "Devolvido para correção",
          "reported": "Laudo liberado", "cancelled": "Cancelado"}
FLAGS = {"missing_images": "Imagens ausentes", "incomplete_series": "Séries incompletas",
         "identity_mismatch": "Identificação divergente", "artifacts": "Artefatos relevantes",
         "acquisition": "Problema de aquisição", "transmission": "Problema de transmissão",
         "duplicate": "Possível estudo duplicado", "doctor_change": "Solicitação de troca de médico",
         "priority_request": "Solicitação de mudança de prioridade", "other": "Outro"}
REQUESTS = ("doctor_change", "priority_request")                 # pedidos: não bloqueiam o encaminhamento
PRIORITIES = ("routine", "urgent", "stat")
MAX_DOC = 10 * 1024 * 1024
MAX_AUDIO = 20 * 1024 * 1024


# ------------------------------------------------------------------ apoio
def _study(s: Session, study_id: uuid.UUID) -> Study:
    st = s.get(Study, study_id)
    if st is None:
        raise NotFound("Estudo não encontrado.")
    return st


def _prep(s: Session, study_id: uuid.UUID, *, create: bool = True) -> ExamPrep | None:
    p = s.execute(select(ExamPrep).where(ExamPrep.study_id == study_id)).scalar_one_or_none()
    if p is None and create:
        _study(s, study_id)
        p = ExamPrep(study_id=study_id, status="preparing", checklist={})
        s.add(p)
        s.flush()
    return p


def _editable(p: ExamPrep) -> None:
    if p.status == "cancelled":
        raise Conflict("Exame cancelado: preparação encerrada.")
    if p.status == "forwarded":
        raise Conflict("Estudo já encaminhado à fila de laudos.")


def _report(s: Session, study_id: uuid.UUID):
    from vyonix.report.models import Report
    return s.execute(select(Report).where(Report.study_id == study_id)).scalar_one_or_none()


def _assignment(s: Session, study_id: uuid.UUID):
    from vyonix.report.models import Assignment, Physician
    return s.execute(select(Assignment, Physician).join(Physician, Physician.id == Assignment.physician_id)
                     .where(Assignment.study_id == study_id, Assignment.status == "open")).first()


def stage(s: Session, st: Study, p: ExamPrep | None, *, open_flags: int | None = None) -> str:
    r = _report(s, st.id)
    if p is not None and p.status == "cancelled":
        return "cancelled"
    if r is not None and r.status == "final":
        return "reported"
    if p is None:
        return "received"
    if p.status == "returned":
        return "returned"
    if p.status == "forwarded":
        return "assigned" if _assignment(s, st.id) else "forwarded"
    n = open_flags if open_flags is not None else _open_flags(s, st.id)
    return "pending" if n else "preparing"


def _open_flags(s: Session, study_id: uuid.UUID) -> int:
    return s.execute(select(func.count()).select_from(ExamFlag).where(
        ExamFlag.study_id == study_id, ExamFlag.status == "open", ExamFlag.code.not_in(REQUESTS))).scalar() or 0


def priority_of(s: Session, st: Study, p: ExamPrep | None) -> str:
    if st.order_id:
        o = s.get(Order, st.order_id)
        if o is not None:
            return o.priority
    return (p.priority if p is not None else None) or "routine"


# ------------------------------------------------------------------ verificações e checklist
def checklist_items(s: Session, modality: str | None) -> list[dict]:
    from vyonix.settings import service as settings
    cfg = settings.get(s, "ris", "preparation")
    return [i for i in cfg["items"] if not i["modalities"] or (modality or "").upper() in
            [m.upper() for m in i["modalities"]]]


def system_checks(s: Session, st: Study, p: ExamPrep | None) -> list[dict]:
    """Verificações fixas de segurança e integridade (não removíveis por configuração)."""
    from vyonix.pacs import service as pacs
    from vyonix.pacs.models import PacsInstance, PacsStudy
    ps = s.execute(select(PacsStudy).where(PacsStudy.study_uid == st.study_instance_uid)).scalar_one_or_none()
    n = s.execute(select(func.count()).select_from(PacsInstance).where(PacsInstance.study_id == ps.id)).scalar() \
        if ps else 0
    receiving = False
    if ps is not None:
        q = pacs.quality(s, st.study_instance_uid)
        receiving = any(i["code"] == "receiving" for i in q["issues"])
    dup = duplicates(s, st)
    return [
        {"code": "images_received", "label": "Imagens recebidas pelo PACS", "ok": bool(n), "detail": f"{n} imagem(ns)"},
        {"code": "reception_finished", "label": "Recepção encerrada (sem imagens chegando)", "ok": bool(n) and not receiving},
        {"code": "patient_identified", "label": "Estudo associado a um paciente", "ok": st.patient_id is not None},
        {"code": "no_open_flags", "label": "Sem suspeita técnica aberta", "ok": not _open_flags(s, st.id)},
        {"code": "duplicate_checked", "label": "Possível duplicidade analisada",
         "ok": not dup or bool(p is not None and p.duplicate_checked)},
    ]


def set_check(s: Session, study_id: uuid.UUID, code: str, done: bool, *, actor: str, actor_id=None,
              ip=None) -> ExamPrep:
    st = _study(s, study_id)
    if code not in {i["code"] for i in checklist_items(s, st.modality)}:
        raise ValidationFailed("Item do checklist desconhecido para esta modalidade.")
    p = _prep(s, study_id)
    _editable(p)
    cl = dict(p.checklist or {})
    cl[code] = {"done": bool(done), "by": actor[:120], "at": utcnow().isoformat()}
    p.checklist = cl
    if p.status == "returned":
        p.status = "preparing"
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="ris.prep.check", target_type="study",
                 target_id=study_id, details={"item": code, "done": bool(done)})
    return p


# ------------------------------------------------------------------ duplicidade
def duplicates(s: Session, st: Study) -> list[dict]:
    """Outros estudos com o mesmo número de acesso, ou do mesmo paciente com a mesma modalidade e data."""
    conds = []
    if st.accession:
        conds.append(Study.accession == st.accession)
    if st.patient_id and st.study_date and st.modality:
        conds.append((Study.patient_id == st.patient_id) & (Study.study_date == st.study_date) &
                     (Study.modality == st.modality))
    if not conds:
        return []
    rows = s.execute(select(Study).where(Study.id != st.id, or_(*conds))).scalars()
    return [{"study_id": str(x.id), "study_instance_uid": x.study_instance_uid, "accession": x.accession,
             "modality": x.modality, "study_date": x.study_date.isoformat() if x.study_date else None,
             "reason": "mesmo número de acesso" if st.accession and x.accession == st.accession
             else "mesmo paciente, modalidade e data"} for x in rows]


def decide_duplicate(s: Session, study_id: uuid.UUID, *, duplicate_of: uuid.UUID | None, note: str | None,
                     actor: str, actor_id=None, ip=None) -> ExamPrep:
    """Registra a análise: não é duplicado, ou é duplicado de outro estudo (este é cancelado; nada é apagado)."""
    st = _study(s, study_id)
    p = _prep(s, study_id)
    _editable(p)
    if duplicate_of is not None:
        if str(duplicate_of) not in {d["study_id"] for d in duplicates(s, st)}:
            raise ValidationFailed("O estudo indicado não é um possível duplicado deste.")
        p.duplicate_of, p.status = duplicate_of, "cancelled"
        p.reason = f"Duplicado de outro estudo. {(note or '').strip()}".strip()[:300]
    p.duplicate_checked = True
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="ris.prep.duplicate", target_type="study",
                 target_id=study_id, details={"duplicate_of": str(duplicate_of) if duplicate_of else None})
    return p


# ------------------------------------------------------------------ comentários
def add_comment(s: Session, study_id: uuid.UUID, text: str, *, actor: str, actor_id=None, ip=None) -> ExamComment:
    _study(s, study_id)
    text = (text or "").strip()
    if not text or len(text) > 2000:
        raise ValidationFailed("Comentário: 1 a 2000 caracteres.")
    c = ExamComment(study_id=study_id, author=actor[:120], author_id=actor_id, text=text)
    s.add(c)
    s.flush()
    if actor_id:
        mark_read(s, study_id, actor_id)
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="ris.prep.comment", target_type="study",
                 target_id=study_id, details={"comment_id": str(c.id)})         # o texto fica só no comentário
    return c


def mark_read(s: Session, study_id: uuid.UUID, user_id: uuid.UUID) -> None:
    r = s.execute(select(ExamCommentRead).where(ExamCommentRead.study_id == study_id,
                                                ExamCommentRead.user_id == user_id)).scalar_one_or_none()
    if r is None:
        s.add(ExamCommentRead(study_id=study_id, user_id=user_id, last_read_at=utcnow()))
    else:
        r.last_read_at = utcnow()
    s.flush()


def unread(s: Session, user_id: uuid.UUID) -> dict[uuid.UUID, int]:
    reads = {r.study_id: r.last_read_at for r in s.execute(select(ExamCommentRead).where(
        ExamCommentRead.user_id == user_id)).scalars()}
    out: dict[uuid.UUID, int] = {}
    for c in s.execute(select(ExamComment).where(or_(ExamComment.author_id.is_(None),
                                                     ExamComment.author_id != user_id))).scalars():
        if c.created_at > reads.get(c.study_id, datetime.min.replace(tzinfo=c.created_at.tzinfo)):
            out[c.study_id] = out.get(c.study_id, 0) + 1
    return out


# ------------------------------------------------------------------ suspeitas técnicas e pedidos
def add_flag(s: Session, study_id: uuid.UUID, code: str, note: str | None, *, actor: str, actor_id=None,
             ip=None) -> ExamFlag:
    if code not in FLAGS:
        raise ValidationFailed("Tipo de sinalização desconhecido.")
    _study(s, study_id)
    p = _prep(s, study_id)
    if p.status == "cancelled":
        raise Conflict("Exame cancelado.")
    f = ExamFlag(study_id=study_id, code=code, note=(note or "").strip()[:500] or None, status="open",
                 created_by=actor[:120])
    s.add(f)
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="ris.prep.flag", target_type="study",
                 target_id=study_id, details={"code": code, "flag_id": str(f.id)})
    return f


def resolve_flag(s: Session, flag_id: uuid.UUID, *, actor: str, actor_id=None, ip=None) -> ExamFlag:
    f = s.get(ExamFlag, flag_id)
    if f is None:
        raise NotFound("Sinalização não encontrada.")
    if f.status != "open":
        raise Conflict("Sinalização já resolvida.")
    f.status, f.resolved_by, f.resolved_at = "resolved", actor[:120], utcnow()
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="ris.prep.flag_resolved", target_type="study",
                 target_id=f.study_id, details={"code": f.code, "flag_id": str(f.id)})
    return f


# ------------------------------------------------------------------ anexos
def sniff(data: bytes) -> tuple[str, str]:
    """(tipo de mídia, categoria) pelo conteúdo; recusa o resto."""
    if data[:5] == b"%PDF-":
        return "application/pdf", "document"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg", "image"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", "image"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "image"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "audio/webm", "audio"
    if data[:4] == b"OggS":
        return "audio/ogg", "audio"
    if data[4:8] == b"ftyp":
        return "audio/mp4", "audio"
    if data[:3] == b"ID3" or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio/mpeg", "audio"
    raise ValidationFailed("Tipo de arquivo não aceito (PDF, JPEG, PNG, WEBP ou áudio WebM/Ogg/MP4/MP3).")


def _aad(tenant: uuid.UUID, study_id: uuid.UUID) -> bytes:
    return b"vyonix-ris-attachment:" + str(tenant).encode() + b":" + str(study_id).encode()


def add_attachment(s: Session, study_id: uuid.UUID, data: bytes, *, kind: str, filename: str | None, key: bytes,
                   actor: str, actor_id=None, ip=None) -> ExamAttachment:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if kind not in ("document", "photo", "audio"):
        raise ValidationFailed("Tipo de anexo inválido.")
    if not data:
        raise ValidationFailed("Arquivo vazio.")
    media, cat = sniff(data)
    if kind == "audio" and cat != "audio" or kind != "audio" and cat == "audio":
        raise ValidationFailed("O conteúdo do arquivo não corresponde ao tipo de anexo.")
    if kind == "photo" and cat != "image":
        raise ValidationFailed("A foto deve ser uma imagem (JPEG, PNG ou WEBP).")
    if len(data) > (MAX_AUDIO if kind == "audio" else MAX_DOC):
        raise ValidationFailed("Arquivo acima do tamanho permitido (documentos 10 MB, áudio 20 MB).")
    _study(s, study_id)
    p = _prep(s, study_id)
    if p.status == "cancelled":
        raise Conflict("Exame cancelado.")
    name = os.path.basename((filename or "").replace("\\", "/")).strip()[:120] or f"{kind}"
    a = ExamAttachment(study_id=study_id, kind=kind, media_type=media, filename=name, size_bytes=len(data),
                       sha256=hashlib.sha256(data).hexdigest(), nonce=os.urandom(12), ciphertext=b"",
                       created_by=actor[:120], created_by_id=actor_id)
    s.add(a)
    s.flush()
    a.ciphertext = AESGCM(key).encrypt(a.nonce, data, _aad(a.tenant_id, study_id))
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="ris.prep.attachment", target_type="study",
                 target_id=study_id, details={"attachment_id": str(a.id), "kind": kind, "media_type": media,
                                              "size": len(data), "sha256": a.sha256})
    return a


def read_attachment(s: Session, attachment_id: uuid.UUID, *, key: bytes, actor: str, actor_id=None,
                    ip=None) -> tuple[bytes, ExamAttachment]:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    a = s.get(ExamAttachment, attachment_id)
    if a is None:
        raise NotFound("Anexo não encontrado.")
    data = AESGCM(key).decrypt(a.nonce, a.ciphertext, _aad(a.tenant_id, a.study_id))
    if hashlib.sha256(data).hexdigest() != a.sha256:
        raise ValidationFailed("Anexo com integridade violada.")
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="ris.prep.attachment_open", target_type="study",
                 target_id=a.study_id, details={"attachment_id": str(a.id)})
    return data, a


# ------------------------------------------------------------------ prioridade, cancelamento, encaminhamento
def set_priority(s: Session, study_id: uuid.UUID, priority: str, *, reason: str | None, actor: str, actor_id=None,
                 ip=None) -> str:
    if priority not in PRIORITIES:
        raise ValidationFailed("Prioridade inválida (rotina, urgente, imediato).")
    st = _study(s, study_id)
    p = _prep(s, study_id)
    if p.status == "cancelled":
        raise Conflict("Exame cancelado.")
    old = priority_of(s, st, p)
    o = s.get(Order, st.order_id) if st.order_id else None
    if o is not None:
        o.priority = priority
    p.priority = priority
    hit = _assignment(s, study_id)
    if hit is not None:                                            # prazo do médico acompanha a nova prioridade
        from vyonix.report.queue import SLA_HOURS
        a = hit[0]
        a.priority, a.due_at = priority, min(a.due_at, utcnow() + timedelta(hours=SLA_HOURS[priority]))
    for f in s.execute(select(ExamFlag).where(ExamFlag.study_id == study_id, ExamFlag.code == "priority_request",
                                              ExamFlag.status == "open")).scalars():
        f.status, f.resolved_by, f.resolved_at = "resolved", actor[:120], utcnow()
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="ris.prep.priority", target_type="study",
                 target_id=study_id, details={"from": old, "to": priority, "reason": (reason or "")[:300] or None})
    return priority


def cancel(s: Session, study_id: uuid.UUID, reason: str, *, actor: str, actor_id=None, ip=None) -> ExamPrep:
    reason = (reason or "").strip()
    if not reason:
        raise ValidationFailed("Informe a justificativa do cancelamento.")
    p = _prep(s, study_id)
    if p.status == "cancelled":
        raise Conflict("Exame já cancelado.")
    r = _report(s, study_id)
    if r is not None and r.status == "final":
        raise Conflict("Exame com laudo liberado não pode ser cancelado (use adendo).")
    old = p.status
    p.status, p.reason = "cancelled", reason[:300]
    hit = _assignment(s, study_id)
    if hit is not None:
        hit[0].status, hit[0].done_at = "cancelled", utcnow()
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="ris.prep.cancel", target_type="study",
                 target_id=study_id, details={"from": old, "reason": reason[:300]})
    return p


def forward(s: Session, study_id: uuid.UUID, *, actor: str, actor_id=None, ip=None) -> dict[str, Any]:
    """Encaminha à fila de laudos depois das verificações fixas e dos itens obrigatórios; aplica a distribuição."""
    st = _study(s, study_id)
    p = _prep(s, study_id)
    _editable(p)
    missing = [c["label"] for c in system_checks(s, st, p) if not c["ok"]]
    done = p.checklist or {}
    missing += [i["label"] for i in checklist_items(s, st.modality)
                if i["required"] and not (done.get(i["code"]) or {}).get("done")]
    if missing:
        raise ValidationFailed("Ainda não pode ser encaminhado: " + "; ".join(missing) + ".",
                               details={"missing": missing})
    p.status, p.forwarded_at, p.forwarded_by, p.reason = "forwarded", utcnow(), actor[:120], None
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="ris.prep.forward", target_type="study",
                 target_id=study_id)
    from vyonix.report import distribution
    assigned = distribution.auto_assign(s, st, priority=priority_of(s, st, p), actor=actor, actor_id=actor_id, ip=ip)
    return {"status": stage(s, st, p), "assigned_to": assigned}


def return_for_correction(s: Session, study_id: uuid.UUID, reason: str, *, actor: str, actor_id=None,
                          ip=None) -> ExamPrep:
    """O médico (ou a coordenação) devolve o estudo ao técnico; a atribuição aberta é encerrada."""
    reason = (reason or "").strip()
    if not reason:
        raise ValidationFailed("Informe o que precisa ser corrigido.")
    p = _prep(s, study_id)
    if p.status != "forwarded":
        raise Conflict("Só estudo encaminhado pode ser devolvido.")
    r = _report(s, study_id)
    if r is not None and r.status == "final":
        raise Conflict("Laudo já liberado.")
    p.status, p.reason = "returned", reason[:300]
    hit = _assignment(s, study_id)
    if hit is not None:
        hit[0].status, hit[0].done_at = "cancelled", utcnow()
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="ris.prep.return", target_type="study",
                 target_id=study_id, details={"reason": reason[:300]})
    return p


# ------------------------------------------------------------------ compartilhamento interno
def share(s: Session, study_id: uuid.UUID, user_id: uuid.UUID, *, scope: str, hours: int, actor: str,
          actor_id=None, ip=None) -> ExamShare:
    from vyonix.auth.models import User
    if scope not in ("view", "report"):
        raise ValidationFailed("Escopo inválido (view ou report).")
    if not 1 <= hours <= 24 * 30:
        raise ValidationFailed("Prazo do compartilhamento: 1 hora a 30 dias.")
    _study(s, study_id)
    u = s.get(User, user_id)
    if u is None or not u.active:
        raise NotFound("Usuário não encontrado nesta instituição.")
    sh = ExamShare(study_id=study_id, user_id=user_id, scope=scope, expires_at=utcnow() + timedelta(hours=hours),
                   created_by=actor[:120])
    s.add(sh)
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="ris.prep.share", target_type="study",
                 target_id=study_id, details={"user_id": str(user_id), "scope": scope,
                                              "expires_at": sh.expires_at.isoformat()})
    return sh


def shared_studies(s: Session, user_id: uuid.UUID, *, scope: str | None = None) -> set[uuid.UUID]:
    """Estudos compartilhados com o usuário (vigentes). ``scope="report"``: só os que permitem laudar — um
    compartilhamento ``view`` dá apenas leitura (A05-002)."""
    now = utcnow()
    q = select(ExamShare.study_id).where(ExamShare.user_id == user_id, ExamShare.expires_at > now,
                                         ExamShare.revoked_at.is_(None))
    if scope is not None:
        q = q.where(ExamShare.scope == scope)
    return set(s.execute(q).scalars())


def revoke_share(s: Session, share_id: uuid.UUID, *, actor: str, actor_id=None, ip=None) -> None:
    sh = s.get(ExamShare, share_id)
    if sh is None or sh.revoked_at is not None:
        raise NotFound("Compartilhamento não encontrado.")
    sh.revoked_at = utcnow()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="ris.prep.share_revoked", target_type="study",
                 target_id=sh.study_id, details={"share_id": str(sh.id)})


# ------------------------------------------------------------------ fila e detalhe
def queue(s: Session, user_id: uuid.UUID, *, date_from=None, date_to=None, modality: str | None = None,
          station: str | None = None, site_id: uuid.UUID | None = None, stage_filter: str | None = None,
          priority: str | None = None, patient: str | None = None, accession: str | None = None,
          limit: int = 300) -> dict[str, Any]:
    from vyonix.pacs.models import PacsInstance, PacsStudy
    q = select(Study, Patient).outerjoin(Patient, Patient.id == Study.patient_id)
    if date_from:
        q = q.where(Study.created_at >= datetime.combine(date_from, datetime.min.time()).astimezone())
    if date_to:
        q = q.where(Study.created_at < datetime.combine(date_to, datetime.min.time()).astimezone() + timedelta(days=1))
    if modality:
        q = q.where(Study.modality == modality.strip().upper())
    if site_id:
        q = q.where(Study.site_id == site_id)
    if accession:
        q = q.where(Study.accession == accession.strip())
    if patient:
        q = q.where(Patient.name.ilike(f"%{patient.strip()}%"))
    rows = list(s.execute(q.order_by(Study.created_at.desc()).limit(min(limit, 1000))))
    ids = [st.id for st, _p in rows]
    preps = {p.study_id: p for p in s.execute(select(ExamPrep).where(ExamPrep.study_id.in_(ids))).scalars()}
    flags: dict = {}
    for f in s.execute(select(ExamFlag).where(ExamFlag.study_id.in_(ids), ExamFlag.status == "open")).scalars():
        flags.setdefault(f.study_id, []).append(f.code)
    att = dict(s.execute(select(ExamAttachment.study_id, func.count()).where(ExamAttachment.study_id.in_(ids))
                         .group_by(ExamAttachment.study_id)).all())
    uids = [st.study_instance_uid for st, _ in rows]
    pstudies = {ps.study_uid: ps for ps in s.execute(select(PacsStudy).where(PacsStudy.study_uid.in_(uids))).scalars()}
    counts = dict(s.execute(select(PacsStudy.study_uid, func.count(PacsInstance.id)).join(
        PacsInstance, PacsInstance.study_id == PacsStudy.id).where(PacsStudy.study_uid.in_(uids))
        .group_by(PacsStudy.study_uid)).all())
    unread_by = unread(s, user_id)
    items, totals = [], dict.fromkeys(list(STAGES) + ["incomplete", "urgent", "awaiting"], 0)
    from vyonix.pacs import service as pacs
    for st, pat in rows:
        p = preps.get(st.id)
        real_flags = [c for c in flags.get(st.id, []) if c not in REQUESTS]
        stg = stage(s, st, p, open_flags=len(real_flags))
        ps = pstudies.get(st.study_instance_uid)
        src = ps.source_ae if ps is not None else None
        if station and (src or "").upper() != station.strip().upper():
            continue
        incomplete = False
        if ps is not None and stg not in ("reported", "cancelled"):
            incomplete = any(i["code"] in ("receiving", "instance_gap", "instance_repeated")
                             for i in pacs.quality(s, st.study_instance_uid)["issues"])
        pr = priority_of(s, st, p)
        if priority and pr != priority:
            continue
        totals[stg] += 1
        totals["incomplete"] += incomplete
        totals["urgent"] += pr in ("urgent", "stat") and stg not in ("reported", "cancelled")
        totals["awaiting"] += stg in ("received", "preparing")
        if stage_filter and not (stg == stage_filter or (stage_filter == "incomplete" and incomplete) or
                                 (stage_filter == "urgent" and pr in ("urgent", "stat") and
                                  stg not in ("reported", "cancelled")) or
                                 (stage_filter == "awaiting" and stg in ("received", "preparing"))):
            continue
        hit = _assignment(s, st.id)
        items.append({"study_id": str(st.id), "study_instance_uid": st.study_instance_uid,
                      "patient_name": pat.name if pat else None, "accession": st.accession,
                      "modality": st.modality, "description": st.description,
                      "study_date": st.study_date.isoformat() if st.study_date else None,
                      "received_at": st.created_at.isoformat(), "site_id": str(st.site_id) if st.site_id else None,
                      "station": src, "images": counts.get(st.study_instance_uid, 0), "incomplete": incomplete,
                      "stage": stg, "priority": pr, "flags": flags.get(st.id, []),
                      "attachments": int(att.get(st.id, 0)), "unread_comments": unread_by.get(st.id, 0),
                      "physician": hit[1].full_name if hit else None,
                      "due_at": hit[0].due_at.isoformat() if hit else None})
    return {"items": items, "totals": totals, "stages": STAGES}


def detail(s: Session, study_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
    from vyonix.tenancy.models import Organization, Site
    st = _study(s, study_id)
    p = _prep(s, study_id, create=False)
    pat = s.get(Patient, st.patient_id) if st.patient_id else None
    ident = None
    if pat is not None:
        i = s.execute(select(PatientIdentifier).where(PatientIdentifier.patient_id == pat.id)
                      .order_by(PatientIdentifier.issuer)).scalars().first()
        ident = f"{i.value} ({i.issuer})" if i else None
    o = s.get(Order, st.order_id) if st.order_id else None
    enc = None
    if o is not None and o.encounter_id:
        from vyonix.clinical.models import Encounter
        e = s.get(Encounter, o.encounter_id)
        enc = e.number if e else None
    site = s.get(Site, st.site_id) if st.site_id else None
    org = s.execute(select(Organization)).scalar_one_or_none()
    hit = _assignment(s, study_id)
    done = (p.checklist if p else None) or {}
    comments = list(s.execute(select(ExamComment).where(ExamComment.study_id == study_id)
                              .order_by(ExamComment.created_at)).scalars())
    read_at = s.execute(select(ExamCommentRead.last_read_at).where(ExamCommentRead.study_id == study_id,
                                                                   ExamCommentRead.user_id == user_id)).scalar()
    return {
        "study_id": str(st.id), "study_instance_uid": st.study_instance_uid,
        "patient": {"name": pat.name if pat else None, "identifier": ident,
                    "birth_date": pat.birth_date.isoformat() if pat and pat.birth_date else None,
                    "sex": pat.sex if pat else None},
        "encounter": enc, "accession": st.accession or (o.accession if o else None), "modality": st.modality,
        "description": st.description, "institution": org.name if org else None, "site": site.name if site else None,
        "physician": hit[1].full_name if hit else None, "due_at": hit[0].due_at.isoformat() if hit else None,
        "priority": priority_of(s, st, p), "stage": stage(s, st, p), "stage_label": STAGES[stage(s, st, p)],
        "reason": p.reason if p else None,
        "checklist": [{**i, "done": bool((done.get(i["code"]) or {}).get("done")),
                       "by": (done.get(i["code"]) or {}).get("by")} for i in checklist_items(s, st.modality)],
        "system_checks": system_checks(s, st, p),
        "duplicates": duplicates(s, st), "duplicate_checked": bool(p and p.duplicate_checked),
        "attachments": [{"id": str(a.id), "kind": a.kind, "media_type": a.media_type, "filename": a.filename,
                         "size": a.size_bytes, "by": a.created_by, "at": a.created_at.isoformat()}
                        for a in s.execute(select(ExamAttachment).where(ExamAttachment.study_id == study_id)
                                           .order_by(ExamAttachment.created_at)).scalars()],
        "comments": [{"id": str(c.id), "author": c.author, "text": c.text, "at": c.created_at.isoformat(),
                      "institution": org.name if org else None,
                      "unread": c.author_id != user_id and (read_at is None or c.created_at > read_at)}
                     for c in comments],
        "flags": [{"id": str(f.id), "code": f.code, "label": FLAGS.get(f.code, f.code), "note": f.note,
                   "status": f.status, "by": f.created_by, "at": f.created_at.isoformat(),
                   "resolved_by": f.resolved_by} for f in s.execute(select(ExamFlag).where(
                       ExamFlag.study_id == study_id).order_by(ExamFlag.created_at)).scalars()],
        "shares": [{"id": str(x.id), "user_id": str(x.user_id), "scope": x.scope, "expires_at": x.expires_at.isoformat()}
                   for x in s.execute(select(ExamShare).where(ExamShare.study_id == study_id,
                                                              ExamShare.revoked_at.is_(None),
                                                              ExamShare.expires_at > utcnow())).scalars()],
        "flag_types": FLAGS,
    }
