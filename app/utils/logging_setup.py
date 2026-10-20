"""Logging estruturado (JSON Lines) com rotação e redação de dados de paciente.

* Um arquivo por papel de processo (``vyonix-ui.log``, ``vyonix-service.log``) para
  evitar disputa de rotação entre processos.
* O arquivo é aberto em modo *append*: o histórico nunca é sobrescrito a cada execução.
* Toda mensagem, argumento, campo ``extra`` e *traceback* passa pela redação.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
import threading
from pathlib import Path
from typing import Any

from app.security.redaction import redact, redact_text
from app.utils.timeutil import utc_now_iso

ROOT_LOGGER = "vyonix"
_HANDLER_MARK = "_vyonix_handler"

_STANDARD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}

# Antes de setup_logging() (ex.: bibliotecas e testes), nada vai para o stderr por acidente.
logging.getLogger(ROOT_LOGGER).addHandler(logging.NullHandler())


class JsonFormatter(logging.Formatter):
    def __init__(self, role: str) -> None:
        super().__init__()
        self.role = role

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": utc_now_iso(),
            "level": record.levelname,
            "logger": record.name,
            "role": self.role,
            "pid": record.process,
            "thread": record.threadName,
            "msg": redact_text(record.getMessage()),
        }
        extras = {k: v for k, v in record.__dict__.items() if k not in _STANDARD_ATTRS}
        if extras:
            payload["data"] = redact(_jsonable(extras))
        if record.exc_info:
            payload["exc"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


class RedactingConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record))


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value, default=str)
        return value
    except (TypeError, ValueError):
        return str(value)


def setup_logging(
    log_dir: Path,
    role: str,
    level: str = "INFO",
    *,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 10,
    console: bool = False,
) -> Path:
    """Configura o logger ``vyonix``. Idempotente: pode ser chamado novamente."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"vyonix-{role}.log"

    root = logging.getLogger(ROOT_LOGGER)
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARK, False):
            root.removeHandler(handler)
            handler.close()

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, mode="a", maxBytes=max_bytes, backupCount=backup_count,
        encoding="utf-8", delay=True,
    )
    file_handler.setFormatter(JsonFormatter(role))
    setattr(file_handler, _HANDLER_MARK, True)
    root.addHandler(file_handler)

    if console:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(RedactingConsoleFormatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
        setattr(stream, _HANDLER_MARK, True)
        root.addHandler(stream)

    root.propagate = False
    set_log_level(level)
    return log_file


def set_log_level(level: str) -> None:
    logging.getLogger(ROOT_LOGGER).setLevel(getattr(logging, level.upper(), logging.INFO))


def get_logger(name: str) -> logging.Logger:
    if not name.startswith(ROOT_LOGGER):
        name = f"{ROOT_LOGGER}.{name}"
    return logging.getLogger(name)


def shutdown_logging() -> None:
    root = logging.getLogger(ROOT_LOGGER)
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARK, False):
            handler.flush()
            handler.close()
            root.removeHandler(handler)


def install_exception_hooks() -> None:
    """Registra exceções não tratadas (thread principal e threads secundárias)."""
    log = get_logger("crash")

    def _hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.critical("Exceção não tratada", exc_info=(exc_type, exc, tb))

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        log.critical(
            "Exceção não tratada em thread %s", getattr(args.thread, "name", "?"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _hook
    threading.excepthook = _thread_hook
