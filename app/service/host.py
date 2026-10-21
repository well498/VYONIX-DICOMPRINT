"""Núcleo do serviço Windows (Fase 7), sem Qt e sem pywin32 — testável em qualquer sistema.

O ``ServiceHost`` inicializa o VYONIX com ``role="service"`` (logs em ProgramData), inicia o
``CoreRuntime`` (Storage SCP, Print SCP, fila de impressão, retenção), publica o canal de controle
(``ipc``) e observa o banco: configurações alteradas pela interface (outro processo) são aplicadas
sem reiniciar o serviço.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from app import __version__
from app.service.ipc import IpcServer
from app.utils.logging_setup import get_logger

log = get_logger("service.host")

SETTINGS_POLL_S = 2.0


class ServiceHost:
    def __init__(self, data_dir: str | None = None) -> None:
        self.data_dir = data_dir
        self.ctx = None
        self.ipc: IpcServer | None = None
        self._stop = threading.Event()
        self._watch: threading.Thread | None = None
        self._last_settings: dict[str, Any] = {}
        self.started_at: float | None = None

    # ------------------------------------------------------------------ ciclo de vida
    def start(self) -> None:
        from app.bootstrap import bootstrap
        from app.database.repositories.events_repo import Category
        self.ctx = bootstrap(data_dir=self.data_dir, role="service")
        self.ctx.runtime.start()
        self._last_settings = self.ctx.settings.get_all()
        self.ipc = IpcServer(self.ctx.paths.machine_root, self._handlers())
        self.ipc.start()
        self._stop.clear()
        self._watch = threading.Thread(target=self._watch_settings, name="vyonix-settings-watch", daemon=True)
        self._watch.start()
        self.started_at = time.time()
        self.ctx.events.add(level="INFO", category=Category.SYSTEM, action="service.start",
                            message=f"Serviço VYONIX {__version__} iniciado.", actor="system")
        log.info("Serviço iniciado")

    def stop(self) -> None:
        self._stop.set()
        if self._watch is not None:
            self._watch.join(timeout=5)
        if self.ipc is not None:
            self.ipc.stop()
        if self.ctx is not None:
            from app.database.repositories.events_repo import Category
            try:
                self.ctx.events.add(level="INFO", category=Category.SYSTEM, action="service.stop",
                                    message="Serviço VYONIX parado.", actor="system")
            except Exception:  # noqa: BLE001
                pass
            self.ctx.close()
            self.ctx = None

    def wait(self, timeout: float | None = None) -> bool:
        return self._stop.wait(timeout)

    # ------------------------------------------------------------------ configurações
    def _watch_settings(self) -> None:
        while not self._stop.wait(SETTINGS_POLL_S):
            self.reload_settings()
        if self.ctx is not None:
            self.ctx.db.close_thread_connection()

    def reload_settings(self) -> list[str]:
        """Aplica configurações alteradas por outro processo (a interface)."""
        try:
            current = self.ctx.settings.get_all()
        except Exception:  # noqa: BLE001
            log.exception("Falha ao ler configurações")
            return []
        changed = {k: v for k, v in current.items() if self._last_settings.get(k) != v}
        self._last_settings = current
        if changed:
            log.info("Configurações alteradas pela interface", extra={"keys": sorted(changed)})
            self.ctx.runtime.on_settings_changed(changed)
            if "logging.level" in changed:
                from app.utils.logging_setup import set_log_level
                set_log_level(changed["logging.level"])
        return sorted(changed)

    # ------------------------------------------------------------------ comandos
    def _handlers(self) -> dict:
        ctx = self.ctx

        def status(_args):
            return {
                "version": __version__,
                "uptime_s": round(time.time() - (self.started_at or time.time())),
                "services": [{"name": s.name, "state": s.state.value, "detail": s.detail,
                              "since": s.since.isoformat() if s.since else None}
                             for s in ctx.runtime.service_statuses()],
                "storage_bound": ctx.storage_scp.bound, "print_bound": ctx.print_scp.bound,
                "associations": ctx.storage_scp.active_associations(),
                "accepted_ts": ctx.storage_scp.accepted_ts,
                "current_job": ctx.worker.current_job,
            }

        def run(fn):
            def handler(_args):
                fn()
                return status(_args)
            return handler

        def wake(_args):
            ctx.jobs.wakeup.set()
            return True

        def printers(_args):
            return [p.name for p in ctx.printers.refresh()]

        return {
            "ping": lambda _a: "pong",
            "status": status,
            "storage.start": run(ctx.storage_scp.start), "storage.stop": run(ctx.storage_scp.stop),
            "storage.restart": run(ctx.storage_scp.restart),
            "print.start": run(ctx.print_scp.start), "print.stop": run(ctx.print_scp.stop),
            "print.restart": run(ctx.print_scp.restart),
            "settings.reload": lambda _a: self.reload_settings(),
            "jobs.wake": wake,
            "printers.refresh": printers,
        }
