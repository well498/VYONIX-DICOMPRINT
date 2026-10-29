"""Frases rápidas (textos prontos) do editor de laudos.

* **Da instituição** (``owner_user_id`` vazio): criadas e mantidas por quem tem ``report.phrases.manage``; todos que
  redigem laudos usam.
* **Pessoais**: do próprio médico (``report.phrases.own``); só ele vê, usa e altera. Ninguém — nem o administrador —
  lê ou altera a frase pessoal de outro médico pela API.
* Conteúdo em texto rico seguro (``richtext``), com atalho opcional (ex.: ``/normal``) e modalidade opcional.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from vyonix.audit import service as audit
from vyonix.errors import Conflict, NotFound, ValidationFailed
from vyonix.report import richtext
from vyonix.report.models import Phrase

MAX_BODY = 20000
MAX_PER_OWNER = 500
_SHORTCUT = re.compile(r"^/?[a-z0-9][a-z0-9._-]{0,28}$")


def _out(p: Phrase) -> dict[str, Any]:
    return {"id": str(p.id), "title": p.title, "shortcut": p.shortcut, "modality": p.modality, "body": p.body,
            "text": richtext.to_text(p.body, "html"), "active": p.active, "personal": p.owner_user_id is not None}


def listing(s: Session, *, user_id: uuid.UUID | None, modality: str | None = None, include_inactive: bool = False,
            scope: str = "all") -> list[dict[str, Any]]:
    """Frases visíveis para o usuário: da instituição e as pessoais dele. ``scope``: all | own | institution."""
    q = select(Phrase).order_by(Phrase.title)
    if scope == "own":
        q = q.where(Phrase.owner_user_id == user_id)
    elif scope == "institution":
        q = q.where(Phrase.owner_user_id.is_(None))
    else:
        q = q.where((Phrase.owner_user_id.is_(None)) | (Phrase.owner_user_id == user_id))
    if not include_inactive:
        q = q.where(Phrase.active.is_(True))
    out = []
    for p in s.execute(q).scalars():
        if modality and p.modality and p.modality != modality.upper():
            continue
        out.append(_out(p))
    return out


def get(s: Session, phrase_id: uuid.UUID, *, user_id: uuid.UUID | None) -> Phrase:
    p = s.get(Phrase, phrase_id)
    if p is None or (p.owner_user_id is not None and p.owner_user_id != user_id):
        raise NotFound("Frase não encontrada.")                   # pessoal de outro médico: como se não existisse
    return p


def save(s: Session, *, title: str, body: str, shortcut: str | None = None, modality: str | None = None,
         active: bool = True, owner_user_id: uuid.UUID | None, phrase_id: uuid.UUID | None = None,
         user_id: uuid.UUID | None, actor: str, actor_id=None, ip=None) -> Phrase:
    """Cria ou altera. ``owner_user_id`` define se é pessoal (do usuário) ou da instituição (``None``); a frase não
    muda de dono numa alteração."""
    title = (title or "").strip()
    if not 1 <= len(title) <= 120:
        raise ValidationFailed("Título da frase: 1 a 120 caracteres.")
    if len(body or "") > MAX_BODY:
        raise ValidationFailed(f"Texto da frase: até {MAX_BODY} caracteres.")
    clean = richtext.sanitize(body or "")
    if not richtext.to_text(clean, "html").strip():
        raise ValidationFailed("A frase está vazia.")
    sc = (shortcut or "").strip().lower() or None
    if sc is not None:
        if not _SHORTCUT.match(sc):
            raise ValidationFailed("Atalho: letras minúsculas, números, ponto, hífen ou sublinhado (até 30).")
        sc = sc if sc.startswith("/") else "/" + sc
    p = None
    if phrase_id is not None:
        p = get(s, phrase_id, user_id=user_id)
        if p.owner_user_id != owner_user_id:
            raise NotFound("Frase não encontrada.")
    else:
        n = len(s.execute(select(Phrase.id).where(Phrase.owner_user_id == owner_user_id if owner_user_id
                                                  else Phrase.owner_user_id.is_(None))).all())
        if n >= MAX_PER_OWNER:
            raise ValidationFailed(f"Limite de {MAX_PER_OWNER} frases atingido.")
    if sc is not None:
        same = select(Phrase).where(Phrase.shortcut == sc, Phrase.active.is_(True),
                                    (Phrase.owner_user_id == owner_user_id) if owner_user_id
                                    else Phrase.owner_user_id.is_(None))
        other = s.execute(same).scalars().first()
        if other is not None and other is not p:
            raise Conflict(f"O atalho {sc} já está em uso.")
    if p is None:
        p = Phrase(owner_user_id=owner_user_id, title=title, body=clean, created_by=actor[:120])
        s.add(p)
    p.title, p.body, p.shortcut, p.active = title, clean, sc, bool(active)
    p.modality = (modality or "").strip().upper()[:16] or None
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="report.phrase.save", target_type="report_phrase",
                 target_id=p.id, details={"personal": owner_user_id is not None, "active": p.active})
    return p


def delete(s: Session, phrase_id: uuid.UUID, *, user_id: uuid.UUID | None, actor: str, actor_id=None,
           ip=None) -> None:
    """Remove a frase (não afeta laudos já escritos: o texto foi copiado para o laudo)."""
    p = get(s, phrase_id, user_id=user_id)
    personal = p.owner_user_id is not None
    s.delete(p)
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="report.phrase.delete",
                 target_type="report_phrase", target_id=phrase_id, details={"personal": personal})
