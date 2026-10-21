"""Serviço Windows ``VyonixDicomPrint`` (pywin32). Roda na sessão 0, sem interface gráfica.

Comandos (executável ``VyonixService.exe``, como administrador)::

    VyonixService.exe --startup delayed install   # instala (início automático atrasado)
    VyonixService.exe start | stop | restart | remove
    VyonixService.exe debug                         # executa no console (diagnóstico)
    VyonixService.exe --foreground [--data-dir D]   # executa sem o Gerenciador de Serviços (testes)

Sem argumentos, o executável é iniciado pelo Gerenciador de Serviços do Windows.
"""

from __future__ import annotations

import sys

SERVICE_NAME = "VyonixDicomPrint"
DISPLAY_NAME = "VYONIX DICOM Print"
DESCRIPTION = ("Recepção DICOM (Storage SCP), impressão DICOM (Print SCP) e fila de impressão do VYONIX. "
               "Versão de homologação, não validada para uso clínico.")


def run_foreground(argv: list[str]) -> int:
    """Executa o núcleo do serviço no console (sem o Gerenciador de Serviços)."""
    import argparse
    import signal

    from app.service.host import ServiceHost

    p = argparse.ArgumentParser(prog="VyonixService")
    p.add_argument("--foreground", action="store_true")
    p.add_argument("--data-dir")
    p.add_argument("--seconds", type=float, default=0, help="encerra após N segundos (testes)")
    args = p.parse_args(argv)
    host = ServiceHost(args.data_dir)
    host.start()
    stop = {"flag": False}

    def _sig(*_a):
        stop["flag"] = True
        host._stop.set()
    signal.signal(signal.SIGINT, _sig)
    try:
        signal.signal(signal.SIGTERM, _sig)
    except (AttributeError, ValueError):
        pass
    try:
        host.wait(args.seconds or None)
    finally:
        host.stop()
    return 0


def _service_class():
    import servicemanager
    import win32event
    import win32service
    import win32serviceutil

    class VyonixService(win32serviceutil.ServiceFramework):
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = DISPLAY_NAME
        _svc_description_ = DESCRIPTION

        def __init__(self, args):
            super().__init__(args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)
            self.host = None

        def SvcStop(self):  # noqa: N802 - API pywin32
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self.stop_event)

        def SvcShutdown(self):  # noqa: N802 - desligamento do Windows
            self.SvcStop()

        def SvcDoRun(self):  # noqa: N802
            from app.service.host import ServiceHost
            servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE, servicemanager.PYS_SERVICE_STARTED,
                                  (self._svc_name_, ""))
            try:
                self.host = ServiceHost()
                self.host.start()
            except Exception as exc:  # noqa: BLE001
                servicemanager.LogErrorMsg(f"{DISPLAY_NAME}: falha ao iniciar: {exc}")
                raise
            win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)
            try:
                self.host.stop()
            finally:
                servicemanager.LogMsg(servicemanager.EVENTLOG_INFORMATION_TYPE,
                                      servicemanager.PYS_SERVICE_STOPPED, (self._svc_name_, ""))

    return VyonixService


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--foreground" in argv:
        return run_foreground(argv[1:])
    if sys.platform != "win32":
        print("O serviço Windows só existe no Windows. Use --foreground para executar o núcleo.", file=sys.stderr)
        return 2
    import servicemanager
    import win32serviceutil
    cls = _service_class()
    if len(argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(cls)
        servicemanager.StartServiceCtrlDispatcher()
        return 0
    win32serviceutil.HandleCommandLine(cls, argv=argv)
    return 0
