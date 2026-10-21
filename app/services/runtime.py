"""Núcleo em execução: serviços DICOM e tarefas periódicas.

Na Fase 7 este mesmo objeto roda dentro do serviço Windows; até lá, dentro do processo da
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
SCP_RESTART_KEYS = {"dicom.storage.ae_title", "dicom.storage.bind_address", "dicom.storage.port",
                    "dicom.storage.max_associations"}


class CoreRuntime:
    def __init__(self, *, storage_scp, retention, settings_get: Callable[[str], Any], worker=None,
                 printers=None) -> None:
        self.storage_scp = storage_scp
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
        self._stop.clear()
        self._thread = threading.Thread(target=self._periodic, name="vyonix-periodic", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self.started:
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self.storage_scp.stop()
        if self.worker is not None:
            self.worker.stop()
        self.started = False

    def on_settings_changed(self, changed: Mapping[str, Any]) -> None:
        """Reinicia o SCP quando endereço, porta ou AE Title mudam."""
        if self.started and SCP_RESTART_KEYS & set(changed) and \
                self.storage_scp.status().state == ServiceState.RUNNING:
            log.info("Reiniciando Storage SCP após mudança de configuração")
            threading.Thread(target=self.storage_scp.restart, name="vyonix-scp-restart",
                             daemon=True).start()

    def service_statuses(self, _settings=None) -> list[ServiceStatus]:
        return [
            self.storage_scp.status(),
            self._queue_status(),
            ServiceStatus("DICOM Print SCP", ServiceState.NOT_IMPLEMENTED, "Previsto na Fase 5"),
            ServiceStatus("Serviço Windows", ServiceState.NOT_IMPLEMENTED,
                          "Previsto na Fase 7 (hoje os serviços rodam com a interface aberta)"),
        ]

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
