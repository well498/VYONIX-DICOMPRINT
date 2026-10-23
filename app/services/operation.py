"""Pausa operacional do sistema — "Pausar sistema" / "Retomar sistema" (Prompt Mestre §19).

Pausa **segura**, pensada para não perder nada nem interromper o que está em andamento:

* a recepção DICOM continua aceitando imagens (o equipamento não recebe erro e nada se perde);
* trabalhos novos continuam sendo criados e ficam **na fila**;
* o processador da fila conclui o trabalho que já estava em andamento e não inicia outro;
* o acompanhamento do spooler continua (o que já foi enviado é confirmado normalmente);
* ao retomar, a fila segue na ordem de prioridade e chegada.

O estado fica no banco porque a interface e o serviço Windows são processos diferentes. Pausar
e retomar exigem identificação de quem fez; pausar exige um motivo. Ambos ficam na trilha de
auditoria (categoria Administração, mantida pelo prazo próprio de auditoria).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from app.core.errors import ValidationError
from app.database.connection import Database
from app.database.repositories.events_repo import Category, EventRepository
from app.utils.timeutil import utc_now_iso

REASON_MAX = 200
CACHE_S = 1.0


@dataclass(frozen=True)
class OperationState:
    paused: bool
    since: str | None = None
    actor: str | None = None
    reason: str | None = None


class OperationControl:
    def __init__(self, db: Database, events: EventRepository) -> None:
        self.db = db
        self.events = events
        self._listeners: list[Callable[[OperationState], None]] = []
        self._lock = threading.Lock()
        self._cached: tuple[float, bool] | None = None

    def subscribe(self, fn: Callable[[OperationState], None]) -> None:
        self._listeners.append(fn)

    def state(self) -> OperationState:
        r = self.db.connection().execute(
            "SELECT paused, since, actor, reason FROM operation_state WHERE id = 1").fetchone()
        if r is None:
            return OperationState(False)
        return OperationState(bool(r["paused"]), r["since"], r["actor"], r["reason"])

    def is_paused(self) -> bool:
        """Consulta barata para o laço do processador (no máximo uma leitura por segundo)."""
        now = time.monotonic()
        with self._lock:
            if self._cached is not None and now - self._cached[0] < CACHE_S:
                return self._cached[1]
        paused = self.state().paused
        with self._lock:
            self._cached = (now, paused)
        return paused

    def pause(self, *, actor: str, reason: str) -> OperationState:
        actor = (actor or "").strip()
        reason = " ".join((reason or "").split())
        if not actor:
            raise ValidationError("Identifique quem está pausando o sistema.", field="actor")
        if not reason:
            raise ValidationError("Informe o motivo da pausa.", field="reason")
        if len(reason) > REASON_MAX:
            raise ValidationError(f"O motivo deve ter até {REASON_MAX} caracteres.", field="reason")
        current = self.state()
        if current.paused:
            return current
        with self.db.transaction():
            self.db.connection().execute(
                "UPDATE operation_state SET paused = 1, since = ?, actor = ?, reason = ? WHERE id = 1",
                (utc_now_iso(), actor, reason))
            self.events.add(level="WARNING", category=Category.ADMIN, action="operation.pause",
                            message=f"Sistema pausado: {reason}", actor=actor)
        return self._changed()

    def resume(self, *, actor: str) -> OperationState:
        actor = (actor or "").strip()
        if not actor:
            raise ValidationError("Identifique quem está retomando o sistema.", field="actor")
        current = self.state()
        if not current.paused:
            return current
        with self.db.transaction():
            self.db.connection().execute(
                "UPDATE operation_state SET paused = 0, since = NULL, actor = NULL, reason = NULL WHERE id = 1")
            self.events.add(level="INFO", category=Category.ADMIN, action="operation.resume",
                            message="Sistema retomado: a fila de impressão voltou a ser processada.", actor=actor,
                            details={"paused_since": current.since, "paused_by": current.actor,
                                     "reason": current.reason})
        return self._changed()

    def _changed(self) -> OperationState:
        with self._lock:
            self._cached = None
        st = self.state()
        for fn in list(self._listeners):
            try:
                fn(st)
            except Exception:  # noqa: BLE001 - um ouvinte com falha não desfaz a pausa
                pass
        return st
