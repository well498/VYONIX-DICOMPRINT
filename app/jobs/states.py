"""Máquina de estados dos trabalhos de impressão (§12).

Decisões:

* ``SPOOLED`` (enviado ao spooler) e ``COMPLETED`` (impressão confirmada) são
  estados distintos. ``COMPLETED`` só é atingido com confirmação confiável do
  driver/impressora; sem ela, o trabalho permanece em ``SPOOLED``.
* ``COMPLETED`` e ``CANCELLED`` são terminais. Reimprimir cria um **novo** trabalho
  (nova chave de idempotência, ação explícita do usuário) — isso impede impressão
  duplicada por reprocessamento acidental.
* Reprocessar/retentar leva ``FAILED`` de volta a ``VALIDATING``.
* Liberar leva ``HELD`` de volta a ``VALIDATING``.

Os valores abaixo são espelhados por um ``CHECK`` na tabela ``jobs``; o teste
``tests/test_job_states.py`` garante que ambos permaneçam iguais.
"""

from __future__ import annotations

import enum

from app.core.errors import InvalidStateTransition


class JobState(str, enum.Enum):
    RECEIVED = "received"
    VALIDATING = "validating"
    PROCESSING = "processing"
    WAITING_PRINT = "waiting_print"
    SPOOLED = "spooled"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    HELD = "held"

    @property
    def label(self) -> str:
        return LABELS[self]

    @property
    def is_terminal(self) -> bool:
        return not TRANSITIONS[self]


LABELS: dict[JobState, str] = {
    JobState.RECEIVED: "Recebido",
    JobState.VALIDATING: "Validando",
    JobState.PROCESSING: "Processando",
    JobState.WAITING_PRINT: "Aguardando impressão",
    JobState.SPOOLED: "Enviado ao sistema de impressão",
    JobState.COMPLETED: "Concluído",
    JobState.FAILED: "Falhou",
    JobState.CANCELLED: "Cancelado",
    JobState.HELD: "Retido",
}

_S = JobState
TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    _S.RECEIVED: frozenset({_S.VALIDATING, _S.FAILED, _S.CANCELLED, _S.HELD}),
    _S.VALIDATING: frozenset({_S.PROCESSING, _S.FAILED, _S.CANCELLED, _S.HELD}),
    _S.PROCESSING: frozenset({_S.WAITING_PRINT, _S.FAILED, _S.CANCELLED, _S.HELD}),
    _S.WAITING_PRINT: frozenset({_S.SPOOLED, _S.FAILED, _S.CANCELLED, _S.HELD}),
    _S.SPOOLED: frozenset({_S.COMPLETED, _S.FAILED}),
    _S.FAILED: frozenset({_S.VALIDATING, _S.CANCELLED, _S.HELD}),
    _S.HELD: frozenset({_S.VALIDATING, _S.CANCELLED}),
    _S.COMPLETED: frozenset(),
    _S.CANCELLED: frozenset(),
}

# Estados em que um trabalho interrompido por queda do processo precisa ser
# reavaliado na reinicialização (recuperação — Fase 4).
IN_FLIGHT: frozenset[JobState] = frozenset({_S.VALIDATING, _S.PROCESSING, _S.WAITING_PRINT})

# Estados considerados "na fila" pelo Dashboard.
QUEUED: frozenset[JobState] = frozenset(
    {_S.RECEIVED, _S.VALIDATING, _S.PROCESSING, _S.WAITING_PRINT, _S.HELD}
)


def can_transition(current: JobState, target: JobState) -> bool:
    return target in TRANSITIONS[current]


def assert_transition(current: JobState, target: JobState) -> None:
    if not can_transition(current, target):
        raise InvalidStateTransition(
            f"Transição não permitida: {current.label} → {target.label}"
        )
