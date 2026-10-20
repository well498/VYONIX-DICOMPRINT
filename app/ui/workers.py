"""Execução de operações de banco/serviço fora da *thread* da interface (§13).

``run_async(fn, on_done, on_error)`` executa ``fn`` em um ``QThreadPool`` dedicado e
entrega o resultado na *thread* da interface por meio de sinais Qt.
"""

from __future__ import annotations

from typing import Any, Callable

from app.ui.qt import QObject, QRunnable, QThreadPool, Signal

from app.utils.logging_setup import get_logger

log = get_logger("ui.workers")

_pool: QThreadPool | None = None
_active: set["_Task"] = set()


def pool() -> QThreadPool:
    global _pool
    if _pool is None:
        _pool = QThreadPool()
        _pool.setMaxThreadCount(4)
    return _pool


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(object)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.fn = fn
        self.signals = _Signals()

    def run(self) -> None:  # executa em thread secundária
        try:
            result = self.fn()
        except Exception as exc:  # noqa: BLE001 - entregue ao chamador
            log.debug("Operação assíncrona falhou", exc_info=True)
            self.signals.failed.emit(exc)
        else:
            self.signals.done.emit(result)


def run_async(fn: Callable[[], Any], on_done: Callable[[Any], None] | None = None,
              on_error: Callable[[BaseException], None] | None = None) -> None:
    task = _Task(fn)
    _active.add(task)

    def _finish(_: object = None) -> None:
        _active.discard(task)

    if on_done:
        task.signals.done.connect(on_done)
    if on_error:
        task.signals.failed.connect(on_error)
    else:
        task.signals.failed.connect(
            lambda exc: log.error("Operação assíncrona falhou: %s", exc))
    task.signals.done.connect(_finish)
    task.signals.failed.connect(_finish)
    pool().start(task)


def wait_all(timeout_ms: int = 10000) -> bool:
    """Aguarda as operações pendentes (usado no encerramento, antes de fechar o banco)."""
    return pool().waitForDone(timeout_ms)
