"""Núcleo em execução: serviços DICOM e tarefas periódicas.

Roda dentro do serviço Windows (``role="service"``) ou, sem o serviço, dentro do processo da
interface. Não importa Qt.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Mapping

from app.core.contracts import ServiceState, ServiceStatus
from app.utils.logging_setup import get_logger

log = get_logger("runtime")

RETENTION_INTERVAL_S = 6 * 3600
RETENTION_FIRST_DELAY_S = 120
PRINT_RESTART_KEYS = {"dicom.print.enabled", "dicom.print.ae_title", "dicom.print.port", "dicom.print.color",
                      "dicom.storage.bind_address", "dicom.storage.max_associations"}
SCP_RESTART_KEYS = {"dicom.storage.ae_title", "dicom.storage.bind_address", "dicom.storage.port",
                    "dicom.storage.max_associations"}


class CoreRuntime:
    def __init__(self, *, storage_scp, retention, settings_get: Callable[[str], Any], worker=None,
                 printers=None, print_scp=None, role: str = "ui") -> None:
        self.role = role
        self.storage_scp = storage_scp
        self.print_scp = print_scp
        self.worker = worker
        self.printers = printers
        self.retention = retention
        self.get = settings_get
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.started = False

    def start(self) -> None:
        if self.started:
            return
        self.started = True
        if self.printers is not None:
            try:
                self.printers.refresh()
            except Exception:  # noqa: BLE001
                log.exception("Falha ao listar impressoras")
        if self.worker is not None:
            self.worker.start()
        if self.get("dicom.storage.autostart"):
            self.storage_scp.start()
            if self.print_scp is not None:
                self.print_scp.start()
        self._stop.clear()
        self._thread = threading.Thread(target=self._periodic, name="vyonix-periodic", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Para tudo o que estiver rodando — inclusive serviços iniciados fora de ``start()``
        (ex.: pela tela do servidor) —, antes de o banco ser fechado."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self.storage_scp.stop()
        if self.print_scp is not None:
            self.print_scp.stop()
        if self.worker is not None:
            self.worker.stop()
        self.started = False

    def on_settings_changed(self, changed: Mapping[str, Any]) -> None:
        """Reinicia os SCPs quando endereço, porta ou AE Title mudam."""
        self._maybe_restart_print(changed)
        if self.started and SCP_RESTART_KEYS & set(changed) and \
                self.storage_scp.status().state == ServiceState.RUNNING:
            log.info("Reiniciando Storage SCP após mudança de configuração")
            threading.Thread(target=self.storage_scp.restart, name="vyonix-scp-restart",
                             daemon=True).start()

    def _maybe_restart_print(self, changed: Mapping[str, Any]) -> None:
        if self.started and self.print_scp is not None and PRINT_RESTART_KEYS & set(changed):
            threading.Thread(target=self.print_scp.restart, name="vyonix-print-restart", daemon=True).start()

    def service_statuses(self, _settings=None) -> list[ServiceStatus]:
        return [
            self.storage_scp.status(),
            self._queue_status(),
            self.print_scp.status() if self.print_scp is not None else
            ServiceStatus("DICOM Print SCP", ServiceState.NOT_IMPLEMENTED, ""),
            self._windows_service_status(),
        ]

    def _windows_service_status(self) -> ServiceStatus:
        from app.service.remote import WINDOWS_SERVICE, windows_service_state
        state, text = windows_service_state()
        if self.role == "service":
            return ServiceStatus(WINDOWS_SERVICE, ServiceState.RUNNING, "este processo é o serviço")
        if state == "running":
            return ServiceStatus(WINDOWS_SERVICE, ServiceState.ERROR,
                                 "em execução, mas não respondeu à interface; servidores rodando nesta janela")
        return ServiceStatus(WINDOWS_SERVICE, ServiceState.STOPPED,
                             f"{text} — servidores e fila rodando nesta janela (param quando ela fecha)")

    def _queue_status(self) -> ServiceStatus:
        name = "Fila de impressão"
        if self.worker is None:
            return ServiceStatus(name, ServiceState.NOT_IMPLEMENTED, "")
        if not self.worker.running:
            return ServiceStatus(name, ServiceState.STOPPED, "processador parado")
        detail = f"processando o trabalho #{self.worker.current_job}" if self.worker.current_job else "aguardando"
        if self.printers is not None:
            detail += " · " + self.printers.status_summary()
        return ServiceStatus(name, ServiceState.RUNNING, detail)

    def _periodic(self) -> None:
        if self._stop.wait(RETENTION_FIRST_DELAY_S):
            return
        while True:
            try:
                self.retention.purge()
            except Exception:  # noqa: BLE001
                log.exception("Falha na retenção")
            finally:
                self.retention.db.close_thread_connection()
            if self._stop.wait(RETENTION_INTERVAL_S):
                return
