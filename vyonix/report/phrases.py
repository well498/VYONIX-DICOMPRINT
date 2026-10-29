"""Frases rápidas (textos prontos) do editor de laudos.

* **Da instituição** (``owner_user_id`` vazio): criadas e mantidas só por quem tem ``report.phrases.manage``; todos
  que redigem laudos usam.
* **Pessoais**: do próprio médico (``report.phrases.own``); só ele vê, usa, edita, duplica e exclui. Ninguém — nem
  o administrador — lê ou altera a frase pessoal de outro médico pela API. Organizações diferentes nunca se veem
  (row level security por organização).
* **Organização:** categoria, modalidade, busca por título/atalho/texto, **favoritas** e **atalho próprio** por
  usuário (``PhrasePref``) — inclusive para frases da instituição, sem alterá-las para os demais.
* **Duplicar:** cria uma cópia **pessoal** (ponto de partida para personalizar uma frase da instituição).
* **Conteúdo:** texto rico seguro (``richtext``) com dois tipos de campo:
  ``{{paciente.nome}}`` etc. (mesma lista dos modelos; preenchidos com os dados do exame ao inserir) e
  ``[[rótulo]]`` (campo editável: o editor pede o valor ao inserir, p.ex. ``[[medida em mm]]``).
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
from vyonix.report.models import Phrase, PhrasePref

MAX_BODY = 20000
MAX_PER_OWNER = 500
MAX_VARIABLES = 20
_SHORTCUT = re.compile(r"^/?[a-z0-9][a-z0-9._-]{0,28}$")
VARIABLE = re.compile(r"\[\[([^\[\]<>]{1,40})\]\]")


def variables(body: str) -> list[str]:
    """Campos editáveis ``[[rótulo]]`` na ordem em que aparecem (sem repetir)."""
    return list(dict.fromkeys(m.strip() for m in VARIABLE.findall(richtext.to_text(body, "html"))))


def _norm_shortcut(shortcut: str | None) -> str | None:
    sc = (shortcut or "").strip().lower() or None
    if sc is None:
        return None
    if not _SHORTCUT.match(sc):
        raise ValidationFailed("Atalho: letras minúsculas, números, ponto, hífen ou sublinhado (até 30).")
    return sc if sc.startswith("/") else "/" + sc


def _prefs(s: Session, user_id) -> dict[uuid.UUID, PhrasePref]:
    if user_id is None:
        return {}
    return {p.phrase_id: p for p in s.execute(select(PhrasePref).where(PhrasePref.user_id == user_id)).scalars()}


def _out(p: Phrase, pref: PhrasePref | None = None) -> dict[str, Any]:
    mine = pref.shortcut if pref else None
    return {"id": str(p.id), "title": p.title, "shortcut": mine or p.shortcut, "phrase_shortcut": p.shortcut,
            "my_shortcut": mine, "modality": p.modality, "category": p.category, "body": p.body,
            "text": richtext.to_text(p.body, "html"), "variables": variables(p.body), "active": p.active,
            "personal": p.owner_user_id is not None, "favorite": bool(pref and pref.favorite)}


def listing(s: Session, *, user_id: uuid.UUID | None, modality: str | None = None, include_inactive: bool = False,
            scope: str = "all", q: str | None = None, category: str | None = None,
            favorites: bool = False) -> list[dict[str, Any]]:
    """Frases visíveis para o usuário: da instituição e as pessoais dele. ``scope``: all | own | institution.
    Favoritas primeiro; depois por categoria e título."""
    stmt = select(Phrase)
    if scope == "own":
        stmt = stmt.where(Phrase.owner_user_id == user_id)
    elif scope == "institution":
        stmt = stmt.where(Phrase.owner_user_id.is_(None))
    else:
        stmt = stmt.where((Phrase.owner_user_id.is_(None)) | (Phrase.owner_user_id == user_id))
    if not include_inactive:
        stmt = stmt.where(Phrase.active.is_(True))
    prefs = _prefs(s, user_id)
    needle = (q or "").strip().lower()
    out = []
    for p in s.execute(stmt).scalars():
        if modality and p.modality and p.modality != modality.upper():
            continue
        if category and (p.category or "").lower() != category.strip().lower():
            continue
        pref = prefs.get(p.id)
        if favorites and not (pref and pref.favorite):
            continue
        d = _out(p, pref)
        if needle and not any(needle in (x or "").lower() for x in (d["title"], d["shortcut"], d["text"], d["category"])):
            continue
        out.append(d)
    out.sort(key=lambda d: (not d["favorite"], (d["category"] or "~").lower(), d["title"].lower()))
    return out


def categories(s: Session, *, user_id) -> list[str]:
    rows = s.execute(select(Phrase.category).where(Phrase.category.is_not(None),
                                                   (Phrase.owner_user_id.is_(None)) | (Phrase.owner_user_id == user_id))
                     .distinct()).scalars()
    return sorted({r for r in rows if r}, key=str.lower)


def get(s: Session, phrase_id: uuid.UUID, *, user_id: uuid.UUID | None) -> Phrase:
    p = s.get(Phrase, phrase_id)
    if p is None or (p.owner_user_id is not None and p.owner_user_id != user_id):
        raise NotFound("Frase não encontrada.")                   # pessoal de outro médico: como se não existisse
    return p


def _shortcut_free(s: Session, sc: str, *, owner_user_id, user_id, phrase: Phrase | None = None,
                   pref: PhrasePref | None = None) -> None:
    """Um atalho vale uma vez para quem o usa: frases do mesmo dono e atalhos próprios do usuário."""
    if owner_user_id is None:                                      # frase da instituição: entre as da instituição
        other = s.execute(select(Phrase).where(Phrase.shortcut == sc, Phrase.active.is_(True),
                                               Phrase.owner_user_id.is_(None))).scalars().first()
        if other is not None and other is not phrase:
            raise Conflict(f"O atalho {sc} já está em uso.")
        return
    other = s.execute(select(Phrase).where(Phrase.shortcut == sc, Phrase.active.is_(True),
                                           Phrase.owner_user_id == owner_user_id)).scalars().first()
    if other is not None and other is not phrase:
        raise Conflict(f"O atalho {sc} já está em uso.")
    mine = s.execute(select(PhrasePref).where(PhrasePref.user_id == user_id, PhrasePref.shortcut == sc)).scalars().first()
    if mine is not None and mine is not pref:
        raise Conflict(f"O atalho {sc} já está em uso por você.")


def save(s: Session, *, title: str, body: str, shortcut: str | None = None, modality: str | None = None,
         category: str | None = None, active: bool = True, owner_user_id: uuid.UUID | None,
         phrase_id: uuid.UUID | None = None, user_id: uuid.UUID | None, actor: str, actor_id=None,
         ip=None) -> Phrase:
    """Cria ou altera. ``owner_user_id`` define se é pessoal (do usuário) ou da instituição (``None``); a frase não
    muda de dono numa alteração."""
    from vyonix.report import templates as tpl
    title = (title or "").strip()
    if not 1 <= len(title) <= 120:
        raise ValidationFailed("Título da frase: 1 a 120 caracteres.")
    if len(body or "") > MAX_BODY:
        raise ValidationFailed(f"Texto da frase: até {MAX_BODY} caracteres.")
    clean = richtext.sanitize(body or "")
    if not richtext.to_text(clean, "html").strip():
        raise ValidationFailed("A frase está vazia.")
    bad = tpl.unknown_fields(clean)
    if bad:
        raise ValidationFailed(f"Campos desconhecidos na frase: {', '.join(bad)}.",
                               details={"unknown_fields": bad, "allowed": sorted(tpl.FIELDS)})
    if len(variables(clean)) > MAX_VARIABLES:
        raise ValidationFailed(f"Até {MAX_VARIABLES} campos editáveis [[...]] por frase.")
    cat = (category or "").strip()[:60] or None
    sc = _norm_shortcut(shortcut)
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
        _shortcut_free(s, sc, owner_user_id=owner_user_id, user_id=user_id, phrase=p)
    if p is None:
        p = Phrase(owner_user_id=owner_user_id, title=title, body=clean, created_by=actor[:120])
        s.add(p)
    p.title, p.body, p.shortcut, p.active, p.category = title, clean, sc, bool(active), cat
    p.modality = (modality or "").strip().upper()[:16] or None
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="report.phrase.save", target_type="report_phrase",
                 target_id=p.id, details={"personal": owner_user_id is not None, "active": p.active})
    return p


def duplicate(s: Session, phrase_id: uuid.UUID, *, user_id: uuid.UUID, actor: str, actor_id=None,
              ip=None) -> Phrase:
    """Cópia **pessoal** de uma frase visível (da instituição ou própria), sem atalho (para não colidir)."""
    src = get(s, phrase_id, user_id=user_id)
    base = f"{src.title} (cópia)"[:120]
    taken = {t for t in s.execute(select(Phrase.title).where(Phrase.owner_user_id == user_id)).scalars()}
    title, n = base, 2
    while title in taken:
        title, n = f"{src.title} (cópia {n})"[:120], n + 1
    p = save(s, title=title, body=src.body, modality=src.modality, category=src.category, owner_user_id=user_id,
             user_id=user_id, actor=actor, actor_id=actor_id, ip=ip)
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="report.phrase.duplicate",
                 target_type="report_phrase", target_id=p.id, details={"from_institution": src.owner_user_id is None})
    return p


def set_pref(s: Session, phrase_id: uuid.UUID, *, user_id: uuid.UUID, favorite: bool | None = None,
             shortcut: str | None = None, clear_shortcut: bool = False) -> dict[str, Any]:
    """Favorita e atalho próprio do usuário para uma frase visível a ele (não muda a frase para os outros)."""
    p = get(s, phrase_id, user_id=user_id)
    pref = s.execute(select(PhrasePref).where(PhrasePref.user_id == user_id,
                                              PhrasePref.phrase_id == p.id)).scalar_one_or_none()
    if pref is None:
        pref = PhrasePref(user_id=user_id, phrase_id=p.id, favorite=False)
        s.add(pref)
    if favorite is not None:
        pref.favorite = bool(favorite)
    if clear_shortcut:
        pref.shortcut = None
    elif shortcut is not None:
        sc = _norm_shortcut(shortcut)
        if sc is not None:
            _shortcut_free(s, sc, owner_user_id=user_id, user_id=user_id, pref=pref)
            other_own = s.execute(select(Phrase).where(Phrase.shortcut == sc, Phrase.active.is_(True),
                                                       Phrase.owner_user_id.is_(None))).scalars().first()
            if other_own is not None and other_own.id != p.id:
                raise Conflict(f"O atalho {sc} já é de uma frase da instituição.")
        pref.shortcut = sc
    s.flush()
    return _out(p, pref)


def delete(s: Session, phrase_id: uuid.UUID, *, user_id: uuid.UUID | None, actor: str, actor_id=None,
           ip=None) -> None:
    """Remove a frase (não afeta laudos já escritos: o texto foi copiado para o laudo)."""
    p = get(s, phrase_id, user_id=user_id)
    personal = p.owner_user_id is not None
    s.delete(p)                                     # preferências saem junto (ON DELETE CASCADE no banco)
    s.flush()
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="report.phrase.delete",
                 target_type="report_phrase", target_id=phrase_id, details={"personal": personal})
