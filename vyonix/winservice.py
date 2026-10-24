"""Serviços Windows do VYONIX Core (pywin32), sem interface gráfica (sessão 0).

``VyonixPlatform.exe service core --data <pasta>``   → serviço ``VyonixCore`` (API + interface web)
``VyonixPlatform.exe service worker --data <pasta>`` → serviço ``VyonixWorker`` (processador de eventos)
``VyonixPlatform.exe service pacs-engine --data <pasta>`` → serviço ``VyonixPacsEngine`` (Orthanc supervisionado)

O registro dos serviços (conta virtual, recuperação, dependências) é feito pelo VYONIX DEPLOY.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
from pathlib import Path

NAMES = {"core": ("VyonixCore", "VYONIX Core"), "worker": ("VyonixWorker", "VYONIX Worker"),
         "pacs-engine": ("VyonixPacsEngine", "VYONIX PACS (motor DICOM)")}


def _logging(data_dir: Path, which: str) -> None:
    d = data_dir / "logs"
    d.mkdir(parents=True, exist_ok=True)
    h = logging.handlers.RotatingFileHandler(d / f"{which}.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(h)
    root.setLevel(logging.INFO)


class Runner:
    """Executa o Core (uvicorn) ou o processador de eventos numa thread, com parada limpa."""

    def __init__(self, which: str, data_dir: Path) -> None:
        self.which, self.data_dir = which, data_dir
        self.server = None
        self.worker = None
        self.engine = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.which == "pacs-engine":
            from vyonix.pacs.engine_host import CONFIG_NAME, EngineProcess, default_binary
            import json
            cfg_file = self.data_dir / "pacs" / CONFIG_NAME
            storage = Path(json.loads(cfg_file.read_text(encoding="utf-8"))["StorageDirectory"])
            self.engine = EngineProcess(default_binary(), cfg_file, log_file=storage / "logs" / "orthanc.log")
            self.engine.start()
            self.thread = self.engine.thread
            return
        from vyonix import config as config_mod
        from vyonix.context import build
        cfg = config_mod.load(self.data_dir)
        plat = build(cfg)
        if self.which == "core":
            import uvicorn
            from vyonix.api.app import create_app
            from vyonix.cli import ensure_tls
            cert, key = ensure_tls(cfg)
            self.server = uvicorn.Server(uvicorn.Config(create_app(plat), host=cfg.bind, port=cfg.port,
                                                        ssl_certfile=cert, ssl_keyfile=key, log_config=None,
                                                        server_header=False, proxy_headers=False))
            self.thread = threading.Thread(target=self.server.run, name="vyonix-core", daemon=True)
        else:
            from vyonix.events.worker import Worker
            from vyonix.pacs.sync_task import INTERVAL_S, PacsSyncTask
            self.worker = Worker(plat.db, plat.bus, periodic=[(INTERVAL_S, PacsSyncTask(plat))])
            self.thread = threading.Thread(target=self.worker.run_forever, name="vyonix-worker", daemon=True)
        self.thread.start()

    def stop(self, timeout: float = 20) -> None:
        if self.server is not None:
            self.server.should_exit = True
        if self.worker is not None:
            self.worker.stop.set()
        if self.engine is not None:
            self.engine.stop()
        if self.thread is not None:
            self.thread.join(timeout)


def _service_class(which: str, data_dir: Path):
    import servicemanager
    import win32event
    import win32service
    import win32serviceutil

    name, display = NAMES[which]

    class Svc(win32serviceutil.ServiceFramework):
        _svc_name_ = name
        _svc_display_name_ = display

        def __init__(self, args):
            super().__init__(args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)
            self.runner = Runner(which, data_dir)

        def SvcStop(self):  # noqa: N802
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self.stop_event)

        def SvcShutdown(self):  # noqa: N802
            self.SvcStop()

        def SvcDoRun(self):  # noqa: N802
            servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE, servicemanager.PYS_SERVICE_STARTED,
                                  (name, ""))
            try:
                self.runner.start()
            except Exception as exc:  # noqa: BLE001
                logging.getLogger("vyonix").exception("Falha ao iniciar")
                servicemanager.LogErrorMsg(f"{display}: falha ao iniciar: {exc}")
                raise
            while True:
                r = win32event.WaitForSingleObject(self.stop_event, 5000)
                if r == win32event.WAIT_OBJECT_0:
                    break
                if not self.runner.thread.is_alive():          # thread morreu: falha → recuperação do Windows
                    servicemanager.LogErrorMsg(f"{display}: execução interrompida inesperadamente.")
                    raise SystemExit(1)
            self.runner.stop()
            servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE, servicemanager.PYS_SERVICE_STOPPED,
                                  (name, ""))

    return Svc


def main(argv: list[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="VyonixPlatform service")
    p.add_argument("which", choices=sorted(NAMES))
    p.add_argument("--data", required=True)
    p.add_argument("--foreground", action="store_true", help="executa no console (diagnóstico)")
    a = p.parse_args(argv)
    data = Path(a.data)
    _logging(data, a.which)
    if a.foreground or sys.platform != "win32":
        import signal
        r = Runner(a.which, data)
        r.start()
        ev = threading.Event()
        signal.signal(signal.SIGINT, lambda *_: ev.set())
        try:
            while not ev.wait(1):
                if not r.thread.is_alive():
                    return 1
        finally:
            r.stop()
        return 0
    import servicemanager
    servicemanager.Initialize()
    servicemanager.PrepareToHostSingle(_service_class(a.which, data))
    servicemanager.StartServiceCtrlDispatcher()
    return 0
