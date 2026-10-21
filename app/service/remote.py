"""Interface conectada ao serviço Windows (Fase 7).

Quando o serviço está em execução, a interface **não** inicia servidores nem a fila: ela troca o
``CoreRuntime`` local por ``RemoteRuntime`` e os objetos ``storage_scp``/``print_scp`` por
procuradores que falam com o serviço pelo canal de controle. Trabalhos, configurações e cadastros
continuam no banco compartilhado (o serviço observa as mudanças).
"""

from __future__ import annotations

import sys
import threading
import time
from datetime import datetime
from typing import Any

from app.core.contracts import ServiceState, ServiceStatus
from app.service.ipc import IpcClient, ServiceUnavailable
from app.utils.logging_setup import get_logger

log = get_logger("service.remote")

SERVICE_NAME = "VyonixDicomPrint"
SERVICE_DISPLAY = "VYONIX DICOM Print"
WINDOWS_SERVICE = "Serviço Windows"


def windows_service_state() -> tuple[str, str]:
    """Estado do serviço no Gerenciador de Serviços do Windows: (estado, descrição)."""
    if sys.platform != "win32":
        return "absent", "serviço Windows só existe no Windows"
    try:
        import win32service
        import win32serviceutil
    except ImportError:
        return "absent", "pywin32 indisponível"
    try:
        st = win32serviceutil.QueryServiceStatus(SERVICE_NAME)[1]
    except Exception:  # noqa: BLE001 - serviço não instalado
        return "absent", "não instalado"
    names = {win32service.SERVICE_RUNNING: ("running", "em execução"),
             win32service.SERVICE_STOPPED: ("stopped", "instalado, parado"),
             win32service.SERVICE_START_PENDING: ("starting", "iniciando"),
             win32service.SERVICE_STOP_PENDING: ("stopping", "parando")}
    return names.get(st, ("unknown", f"estado {st}"))


class _Cache:
    def __init__(self, client: IpcClient, ttl: float = 1.0) -> None:
        self.client = client
        self.ttl = ttl
        self._value: dict | None = None
        self._at = 0.0
        self._lock = threading.Lock()
        self.error: str | None = None

    def get(self) -> dict | None:
        with self._lock:
            if self._value is not None and time.monotonic() - self._at < self.ttl:
                return self._value
        try:
            value = self.client.call("status")
            self.error = None
        except Exception as exc:  # noqa: BLE001
            value, self.error = None, str(exc)
        with self._lock:
            self._value, self._at = value, time.monotonic()
        return value

    def invalidate(self) -> None:
        with self._lock:
            self._value = None


def _state(name: str) -> ServiceState:
    try:
        return ServiceState(name)
    except ValueError:
        return ServiceState.ERROR


class RemoteSCP:
    """Mesma interface usada pela tela do servidor e pelo autoteste (status/bound/start/stop…)."""

    def __init__(self, cache: _Cache, prefix: str, name: str) -> None:
        self.cache, self.prefix, self.name = cache, prefix, name

    def _info(self) -> dict | None:
        return self.cache.get()

    def status(self) -> ServiceStatus:
        info = self._info()
        if info is None:
            return ServiceStatus(self.name, ServiceState.ERROR, f"serviço inacessível: {self.cache.error}")
        for s in info["services"]:
            if s["name"] == self.name:
                since = datetime.fromisoformat(s["since"]) if s.get("since") else None
                return ServiceStatus(s["name"], _state(s["state"]), s["detail"] + " (no serviço)", since)
        return ServiceStatus(self.name, ServiceState.ERROR, "estado não informado pelo serviço")

    @property
    def bound(self):
        info = self._info()
        key = "storage_bound" if self.prefix == "storage" else "print_bound"
        b = info.get(key) if info else None
        return tuple(b) if b else None

    @property
    def accepted_ts(self) -> list[str]:
        info = self._info()
        return list(info.get("accepted_ts") or []) if info else []

    def active_associations(self) -> list[dict]:
        info = self._info()
        return list(info.get("associations") or []) if info and self.prefix == "storage" else []

    def _cmd(self, action: str) -> None:
        self.cache.client.call(f"{self.prefix}.{action}")
        self.cache.invalidate()

    def start(self) -> None:
        self._cmd("start")

    def stop(self, timeout: float = 10.0) -> None:
        self._cmd("stop")

    def restart(self) -> None:
        self._cmd("restart")


class RemoteRuntime:
    """Substitui o ``CoreRuntime`` da interface quando o serviço está ativo."""

    remote = True

    def __init__(self, cache: _Cache) -> None:
        self.cache = cache
        self.started = True

    def start(self) -> None:
        return

    def stop(self) -> None:
        return

    def on_settings_changed(self, changed) -> None:
        try:
            self.cache.client.call("settings.reload")
        except Exception:  # noqa: BLE001 - o serviço também observa o banco a cada 2 s
            pass
        self.cache.invalidate()

    def wake_queue(self, _job_id=None) -> None:
        try:
            self.cache.client.call("jobs.wake")
        except Exception:  # noqa: BLE001 - o processador da fila também verifica a cada segundo
            pass

    def service_statuses(self, _settings=None) -> list[ServiceStatus]:
        info = self.cache.get()
        if info is None:
            return [ServiceStatus(WINDOWS_SERVICE, ServiceState.ERROR, f"serviço inacessível: {self.cache.error}")]
        out = [ServiceStatus(s["name"], _state(s["state"]), s["detail"],
                             datetime.fromisoformat(s["since"]) if s.get("since") else None)
               for s in info["services"] if s["name"] != WINDOWS_SERVICE]
        out.append(ServiceStatus(WINDOWS_SERVICE, ServiceState.RUNNING,
                                 f"{SERVICE_DISPLAY} {info['version']} em execução há "
                                 f"{info['uptime_s'] // 60} min (servidores e fila rodam no serviço)"))
        return out


def attach(ctx, client: IpcClient | None = None) -> bool:
    """Conecta a interface ao serviço, se ele responder. Retorna True em modo serviço."""
    client = client or IpcClient(ctx.paths.machine_root, timeout=3.0)
    if not client.available():
        return False
    cache = _Cache(client)
    runtime = RemoteRuntime(cache)
    ctx.runtime = runtime
    ctx.storage_scp = RemoteSCP(cache, "storage", "DICOM Storage SCP")
    ctx.print_scp = RemoteSCP(cache, "print", "DICOM Print SCP")
    ctx.dashboard._status_provider = runtime.service_statuses
    ctx.settings.subscribe(runtime.on_settings_changed)
    ctx.jobs.subscribe(runtime.wake_queue)
    log.info("Interface conectada ao serviço")
    return True


def local_service_status(ctx) -> ServiceStatus:
    """Estado mostrado quando a interface roda os servidores (serviço ausente ou parado)."""
    state, text = windows_service_state()
    detail = (f"{text} — os servidores e a fila estão rodando nesta janela e param quando ela fecha"
              if state != "running" else "em execução, mas não respondeu ao canal de controle")
    return ServiceStatus(WINDOWS_SERVICE, ServiceState.STOPPED if state != "running" else ServiceState.ERROR, detail)


__all__ = ["attach", "RemoteRuntime", "RemoteSCP", "ServiceUnavailable", "windows_service_state",
           "local_service_status", "SERVICE_NAME"]
