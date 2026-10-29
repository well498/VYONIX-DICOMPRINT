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
        self.qr = None
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
            from vyonix.api.https_server import make_server
            # HTTPS; quem digitar http:// na mesma porta é redirecionado para https:// (relato de 28/10/2026)
            self.server = make_server(create_app(plat), host=cfg.bind, port=cfg.port, certfile=cert, keyfile=key,
                                      redirect=bool(cfg.extra.get("http_redirect", True)),
                                      log_config=None, server_header=False, proxy_headers=False)
            self.thread = threading.Thread(target=self.server.run, name="vyonix-core", daemon=True)
            qr_port = cfg.extra.get("pacs_qr_port")
            if qr_port:                                    # consulta/recuperação DICOM do PACS (C-FIND/C-MOVE)
                from vyonix.pacs.dimse_qr import QRServer
                self.qr = QRServer(plat, port=int(qr_port), ae_title=cfg.extra.get("pacs_qr_aet", "VYONIX_QR"))
                try:
                    self.qr.start()
                except OSError:
                    logging.getLogger("vyonix").exception("Consulta/recuperação DICOM não iniciou (porta %s)", qr_port)
                    self.qr = None
        else:
            from vyonix.events.worker import build_worker
            self.worker = build_worker(plat)
            self.thread = threading.Thread(target=self.worker.run_forever, name="vyonix-worker", daemon=True)
            # o PostgreSQL rodando como serviço (pg_ctl runservice) não volta sozinho se o processo do banco cair:
            # o Worker encerra com erro e a recuperação do Windows o reinicia — e, por dependência, sobe o banco antes
            db_watchdog(cfg.database_url, stop=self.worker.stop)
        self.thread.start()

    def stop(self, timeout: float = 20) -> None:
        if self.server is not None:
            self.server.should_exit = True
        if self.worker is not None:
            self.worker.stop.set()
        if self.engine is not None:
            self.engine.stop()
        if self.qr is not None:
            self.qr.stop()
        if self.thread is not None:
            self.thread.join(timeout)


WATCHDOG_INTERVAL_S = 10
WATCHDOG_LIMIT_S = 45


def db_watchdog(database_url: str | None, *, stop: threading.Event, on_down=None,
                interval: float = WATCHDOG_INTERVAL_S, limit: float = WATCHDOG_LIMIT_S) -> threading.Thread | None:
    """Vigia a porta do banco local; fora do ar por ``limit`` segundos → ``on_down`` (padrão: encerra o processo com
    código 70 para o Windows reiniciar o serviço, o que sobe primeiro o serviço do banco, que é dependência)."""
    import os
    import socket
    import time
    from urllib.parse import urlsplit
    if not database_url:
        return None
    u = urlsplit(database_url.replace("postgresql+psycopg://", "postgresql://"))
    host, port = u.hostname or "127.0.0.1", u.port or 5432
    if host not in ("127.0.0.1", "localhost", "::1"):
        return None                                   # banco remoto: a recuperação não é deste servidor
    log = logging.getLogger("vyonix.watchdog")

    def down_default():
        log.critical("Banco %s:%s fora do ar há mais de %ss: reiniciando o serviço para subir o banco.", host, port,
                     int(limit))
        logging.shutdown()
        os._exit(70)
    action = on_down or down_default

    def loop():
        since = None
        while not stop.wait(interval):
            try:
                with socket.create_connection((host, port), timeout=3):
                    since = None
            except OSError:
                since = since or time.monotonic()
                if time.monotonic() - since >= limit:
                    action()
                    since = None
    t = threading.Thread(target=loop, name="vyonix-db-watchdog", daemon=True)
    t.start()
    return t


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
