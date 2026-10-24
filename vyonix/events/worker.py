"""Processador de eventos (``vyonix-worker``).

Reivindica lotes da outbox com ``FOR UPDATE SKIP LOCKED`` (vários processadores não pegam o mesmo
evento), entrega a cada consumidor em uma transação própria (papel da aplicação, com o row level security do
tenant do evento) e registra na inbox nessa mesma transação. Falha de um
consumidor: o evento volta à fila com espera crescente (até 1 hora) e o erro fica registrado; os
consumidores que já processaram não repetem. ``LISTEN vyonix_outbox`` acorda o processador assim que
um evento é confirmado; sem notificação, ele confere a fila a cada poucos segundos.
"""

from __future__ import annotations

import logging
import threading
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from vyonix.db.base import utcnow
from vyonix.events.bus import CHANNEL, Bus, Event
from vyonix.events.models import InboxEntry, OutboxEvent

log = logging.getLogger("vyonix.worker")
MAX_BACKOFF_S = 3600


def _event(o: OutboxEvent) -> Event:
    return Event(id=o.id, type=o.type, tenant_id=o.tenant_id, site_id=o.site_id, occurred_at=o.occurred_at,
                 source=o.source, correlation_id=o.correlation_id,
                 subject={"kind": o.subject_kind, "id": o.subject_id} if o.subject_kind else None, data=o.data or {})


def process_batch(db, bus: Bus, limit: int = 50) -> int:
    """Processa até ``limit`` eventos disponíveis. Retorna quantos foram concluídos."""
    done = 0
    with db.service_session() as s:
        rows = list(s.execute(
            select(OutboxEvent).where(OutboxEvent.published_at.is_(None), OutboxEvent.available_at <= utcnow())
            .order_by(OutboxEvent.seq).limit(limit).with_for_update(skip_locked=True)).scalars())
        for o in rows:
            ev = _event(o)
            failed = None
            for sub in bus.consumers_for(o.type):
                seen = s.execute(select(InboxEntry).where(InboxEntry.event_id == o.id,
                                                          InboxEntry.consumer == sub.name)).first()
                if seen:
                    continue
                try:
                    # o consumidor roda com o papel da aplicação, no tenant do evento (RLS aplicado), em
                    # transação própria: efeito + registro na inbox são confirmados juntos
                    with db.session(o.tenant_id) as cs:
                        sub.handler(cs, ev)
                        cs.execute(insert(InboxEntry).values(event_id=o.id, consumer=sub.name, tenant_id=o.tenant_id)
                                   .on_conflict_do_nothing())
                except Exception as exc:  # noqa: BLE001
                    failed = f"{sub.name}: {type(exc).__name__}: {exc}"
                    log.warning("Consumidor %s falhou no evento %s: %s", sub.name, o.id, exc)
                    break
            if failed:
                o.attempts += 1
                o.last_error = failed[:2000]
                o.available_at = utcnow() + timedelta(seconds=min(MAX_BACKOFF_S, 2 ** min(o.attempts, 12)))
            else:
                o.published_at = utcnow()
                o.last_error = None
                done += 1
    return done


class Worker:
    """Processa a outbox e executa tarefas periódicas (``periodic``: lista de (intervalo em s, função))."""

    def __init__(self, db, bus: Bus, *, poll_s: float = 5.0, periodic=None) -> None:
        self.db, self.bus, self.poll_s = db, bus, poll_s
        self.stop = threading.Event()
        self.periodic = [[float(i), fn, 0.0] for i, fn in (periodic or [])]

    def run_periodic(self, now: float | None = None) -> None:
        import time
        now = time.monotonic() if now is None else now
        for task in self.periodic:
            interval, fn, last = task
            if now - last < interval:
                continue
            task[2] = now
            try:
                fn()
            except Exception:  # noqa: BLE001 - uma tarefa com falha não para as outras nem a outbox
                log.exception("Falha na tarefa periódica %s", getattr(fn, "__name__", fn))

    def run_forever(self) -> None:
        import psycopg
        dsn = self.db.service_engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
        listener = None
        while not self.stop.is_set():
            try:
                if listener is None:
                    listener = psycopg.connect(dsn, autocommit=True)
                    listener.execute(f"LISTEN {CHANNEL}")
                while process_batch(self.db, self.bus):
                    pass
                self.run_periodic()
                for _ in listener.notifies(timeout=self.poll_s, stop_after=1):
                    break
            except Exception:  # noqa: BLE001 - o processador não pode morrer
                log.exception("Falha no processador de eventos")
                if listener is not None:
                    try:
                        listener.close()
                    except Exception:  # noqa: BLE001
                        pass
                listener = None
                self.stop.wait(self.poll_s)
        if listener is not None:
            listener.close()
