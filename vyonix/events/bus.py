"""Publicação e consumo de eventos versionados.

``publish`` grava o evento na tabela ``platform.outbox`` **na mesma transação** da alteração que o
originou: se a transação for desfeita, o evento não existe; se o processo cair depois do commit, o
evento continua lá e o ``vyonix-worker`` o entrega. A entrega é *pelo menos uma vez*; cada
consumidor registra o ``id`` do evento em ``platform.inbox`` e ignora repetições.
"""

from __future__ import annotations

import fnmatch
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

from vyonix.db.base import utcnow
from vyonix.db.session import current_tenant
from vyonix.events.models import OutboxEvent

TYPE_RE = re.compile(r"^[a-z]+(\.[a-z_]+)+\.v[1-9][0-9]*$")
CHANNEL = "vyonix_outbox"


@dataclass(frozen=True)
class Event:
    id: uuid.UUID
    type: str
    tenant_id: uuid.UUID
    site_id: uuid.UUID | None
    occurred_at: datetime
    source: str
    correlation_id: str | None
    subject: dict[str, Any] | None
    data: dict[str, Any]

    def envelope(self) -> dict[str, Any]:
        return {"id": str(self.id), "type": self.type, "tenant_id": str(self.tenant_id),
                "site_id": str(self.site_id) if self.site_id else None, "occurred_at": self.occurred_at.isoformat(),
                "source": self.source, "correlation_id": self.correlation_id, "subject": self.subject,
                "data": self.data}


def publish(s: Session, type: str, data: dict[str, Any] | None = None, *, source: str, subject_kind: str | None = None,
            subject_id: Any = None, site_id: uuid.UUID | None = None, correlation_id: str | None = None) -> uuid.UUID:
    if not TYPE_RE.match(type):
        raise ValueError(f"Tipo de evento inválido (use dominio.objeto.acao.vN): {type}")
    tid = s.info.get("tenant_id") or current_tenant()
    ev = OutboxEvent(id=uuid.uuid4(), tenant_id=tid, site_id=site_id, type=type, source=source,
                     occurred_at=utcnow(), correlation_id=correlation_id, subject_kind=subject_kind,
                     subject_id=str(subject_id) if subject_id is not None else None, data=data or {})
    s.add(ev)
    s.flush()
    s.execute(text("SELECT pg_notify(:c, :t)"), {"c": CHANNEL, "t": type})
    return ev.id


Handler = Callable[[Session, Event], None]


@dataclass
class Subscription:
    name: str
    pattern: str
    handler: Handler


@dataclass
class Bus:
    subscriptions: list[Subscription] = field(default_factory=list)

    def subscribe(self, pattern: str, name: str) -> Callable[[Handler], Handler]:
        def deco(fn: Handler) -> Handler:
            if any(sub.name == name for sub in self.subscriptions):
                raise ValueError(f"Consumidor repetido: {name}")
            self.subscriptions.append(Subscription(name, pattern, fn))
            return fn
        return deco

    def consumers_for(self, type: str) -> list[Subscription]:
        return [sub for sub in self.subscriptions if fnmatch.fnmatchcase(type, sub.pattern)]
