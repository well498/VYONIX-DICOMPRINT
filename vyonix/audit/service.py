"""Auditoria encadeada: cada registro guarda o SHA-256 do anterior (por clínica).

A cadeia é serializada por clínica com um bloqueio consultivo da transação, então dois registros
simultâneos nunca apontam para o mesmo anterior. A tabela só aceita inserção (privilégios e
gatilho no banco); ``verify`` recalcula a cadeia e aponta qualquer alteração feita fora do VYONIX.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from vyonix.audit.models import AuditEntry
from vyonix.db.base import utcnow
from vyonix.db.session import current_tenant

GENESIS = "0" * 64


def _canon(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _ts(at: datetime) -> str:
    return at.astimezone(timezone.utc).isoformat(timespec="microseconds")


def entry_hash(prev: str, at: datetime, actor: str, actor_id: Any, action: str, target_type: Any, target_id: Any,
               details: dict, ip: Any) -> str:
    return hashlib.sha256(_canon([prev, _ts(at), actor, str(actor_id) if actor_id else None, action, target_type,
                                  target_id, details, ip])).hexdigest()


def record(s: Session, *, actor: str, action: str, target_type: str | None = None, target_id: Any = None,
           details: dict | None = None, ip: str | None = None, actor_id: uuid.UUID | None = None,
           tenant_id: uuid.UUID | None = None) -> AuditEntry:
    tid = tenant_id or s.info.get("tenant_id") or current_tenant()
    if tid is None:
        raise RuntimeError("Auditoria sem clínica definida.")
    s.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:t, 7))"), {"t": f"audit:{tid}"})
    prev = s.execute(select(AuditEntry.hash).where(AuditEntry.tenant_id == tid).order_by(AuditEntry.seq.desc())
                     .limit(1)).scalar() or GENESIS
    at = utcnow()
    det = json.loads(_canon(details or {}))
    tgt = str(target_id) if target_id is not None else None
    e = AuditEntry(tenant_id=tid, at=at, actor=actor[:120], actor_id=actor_id, action=action, target_type=target_type,
                   target_id=tgt, details=det, ip=ip, prev_hash=prev,
                   hash=entry_hash(prev, at, actor[:120], actor_id, action, target_type, tgt, det, ip))
    s.add(e)
    s.flush()
    return e


def verify(s: Session, tenant_id: uuid.UUID | None = None) -> list[int]:
    """Sequências cujo encadeamento não confere (vazio = íntegra)."""
    tid = tenant_id or s.info.get("tenant_id") or current_tenant()
    bad, prev = [], GENESIS
    for e in s.execute(select(AuditEntry).where(AuditEntry.tenant_id == tid).order_by(AuditEntry.seq)).scalars():
        h = entry_hash(prev, e.at, e.actor, e.actor_id, e.action, e.target_type, e.target_id, e.details, e.ip)
        if e.prev_hash != prev or e.hash != h:
            bad.append(e.seq)
        prev = e.hash
    return bad


def query(s: Session, *, limit: int = 200, before_seq: int | None = None, action: str | None = None,
          target_type: str | None = None, target_id: str | None = None, actor: str | None = None) -> list[AuditEntry]:
    q = select(AuditEntry).order_by(AuditEntry.seq.desc()).limit(min(limit, 1000))
    if before_seq:
        q = q.where(AuditEntry.seq < before_seq)
    if action:
        q = q.where(AuditEntry.action.like(action.replace("*", "%")))
    if target_type:
        q = q.where(AuditEntry.target_type == target_type)
    if target_id:
        q = q.where(AuditEntry.target_id == str(target_id))
    if actor:
        q = q.where(AuditEntry.actor.ilike(f"%{actor}%"))
    return list(s.execute(q).scalars())
