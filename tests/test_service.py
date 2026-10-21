"""Fase 7 — núcleo do serviço, canal de controle e interface conectada ao serviço.

O serviço real (Gerenciador de Serviços do Windows) é verificado pelo pipeline de CI no Windows;
aqui o mesmo núcleo (``ServiceHost``) roda em uma thread, com socket local no lugar do named pipe.
"""

import time
import unittest

try:
    import pynetdicom  # noqa: F401
    import numpy  # noqa: F401
    HAS = True
except ImportError:
    HAS = False

from tests.helpers import TempDirTestCase


@unittest.skipUnless(HAS, "pynetdicom/numpy não instalados")
class ServiceHostTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        from app.bootstrap import bootstrap
        from app.printing.backends.pdf import PDF_PRINTER
        from app.service.host import ServiceHost
        from tests.dicom_helpers import free_port
        self.data = self.tmp / "data"
        prep = bootstrap(data_dir=self.data)
        self.port, self.pport = free_port(), free_port()
        prep.settings.update({"dicom.storage.bind_address": "127.0.0.1", "dicom.storage.port": self.port,
                              "dicom.print.port": self.pport, "printing.default_printer": PDF_PRINTER,
                              "printing.dpi": 150, "jobs.collect_seconds": 2}, actor="t")
        prep.devices.create({"name": "CT", "ae_title": "CT_TESTE", "modality": "CT", "ip_address": "127.0.0.1"},
                            actor="t", authorized=True)
        prep.close()
        self.host = ServiceHost(str(self.data))
        self.host.start()
        self.ui = None

    def tearDown(self):
        if self.ui is not None:
            self.ui.close()
        self.host.stop()
        super().tearDown()

    def wait(self, fn, timeout=20.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            v = fn()
            if v:
                return v
            time.sleep(0.2)
        return fn()

    def test_ipc_status_auth_and_commands(self):
        from app.service.ipc import IpcClient, ServiceUnavailable, key_path
        c = IpcClient(self.host.ctx.paths.machine_root)
        self.assertEqual(c.call("ping"), "pong")
        st = c.call("status")
        names = {s["name"]: s["state"] for s in st["services"]}
        self.assertEqual(names["DICOM Storage SCP"], "running")
        self.assertEqual(names["DICOM Print SCP"], "running")
        self.assertEqual(names["Fila de impressão"], "running")
        self.assertEqual(c.call("storage.stop")["services"][0]["state"], "stopped")
        c.call("storage.start")
        with self.assertRaises(RuntimeError):
            c.call("comando.inexistente")
        good = key_path(self.host.ctx.paths.machine_root).read_bytes()
        key_path(self.host.ctx.paths.machine_root).write_bytes(b"x" * 32)     # chave errada
        with self.assertRaises(ServiceUnavailable):
            IpcClient(self.host.ctx.paths.machine_root, timeout=1).call("ping")
        key_path(self.host.ctx.paths.machine_root).write_bytes(good)
        self.assertTrue(c.available())

    def test_ui_attached_to_service(self):
        from app.bootstrap import bootstrap
        from app.dicom import scu
        from app.jobs.states import JobState
        from app.printing.backends.pdf import PDF_PRINTER
        from app.service import remote
        from tests.dicom_helpers import free_port, make_ct
        self.ui = bootstrap(data_dir=self.data, role="ui")
        self.assertTrue(remote.attach(self.ui))
        # Servidores rodam no serviço; a interface só observa
        self.assertEqual(self.ui.storage_scp.status().state.value, "running")
        self.assertIn("no serviço", self.ui.storage_scp.status().detail)
        self.assertEqual(self.ui.storage_scp.bound, ("127.0.0.1", self.port))
        statuses = {s.name: s for s in self.ui.dashboard.snapshot().services}
        self.assertEqual(statuses["Serviço Windows"].state.value, "running")
        self.assertFalse(self.ui.worker.running)
        # Imagens recebidas pelo serviço são impressas pela fila do serviço
        files = [make_ct(self.tmp / "in/a.dcm")]
        self.assertEqual(scu.store_files("127.0.0.1", self.port, "VYONIX", files, calling_ae="CT_TESTE"), [0])
        job = self.wait(lambda: next((j for j in self.ui.jobs.list() if j.state == JobState.COMPLETED), None))
        self.assertIsNotNone(job, [(j.id, j.state, j.state_reason) for j in self.ui.jobs.list()])
        # Pedido feito na interface (página de teste) é executado pelo serviço
        jid = self.ui.jobs.test_page(printer=PDF_PRINTER, actor="t")
        self.assertTrue(self.wait(lambda: self.ui.jobs.get_job(jid).state == JobState.COMPLETED))
        # Configuração alterada na interface é aplicada pelo serviço (reinicia na nova porta)
        new_port = free_port()
        self.ui.settings.update({"dicom.storage.port": new_port}, actor="t")
        self.assertTrue(self.wait(lambda: self.ui.storage_scp.bound == ("127.0.0.1", new_port)
                                  and self.ui.storage_scp.status().state.value == "running"))
        self.assertTrue(scu.echo("127.0.0.1", new_port, "VYONIX", calling_ae="CT_TESTE")["ok"])
        # Comando da tela do servidor
        self.ui.print_scp.stop()
        self.assertEqual(self.ui.print_scp.status().state.value, "stopped")
        self.ui.print_scp.start()
        self.assertEqual(self.ui.print_scp.status().state.value, "running")

    def test_ui_without_service_runs_locally(self):
        from app.bootstrap import bootstrap
        from app.service import remote
        self.host.stop()
        self.ui = bootstrap(data_dir=self.data, role="ui")
        self.assertFalse(remote.attach(self.ui))
        st = {s.name: s for s in self.ui.runtime.service_statuses()}["Serviço Windows"]
        self.assertEqual(st.state.value, "stopped")
        self.assertIn("nesta janela", st.detail)
        self.host = type("Noop", (), {"stop": lambda self: None})()


class PrinterVisibilityTest(TempDirTestCase):
    """O serviço (Sistema Local) não sobrescreve a impressora padrão vista pelo usuário."""

    def backend(self, names, default=None):
        from app.core.contracts import PrinterInfo

        class B:
            name = "windows"

            def list_printers(self_inner):
                return [PrinterInfo(name=n, driver="drv", is_default=n == default, paper_sizes=("A4",),
                                    resolutions_dpi=(300,), supports_color=False, status_text="pronta") for n in names]
        return B()

    def test_service_keeps_user_default_and_flags_invisible_printers(self):
        from app.bootstrap import bootstrap
        from app.printing.service import PrinterService
        ctx = bootstrap(data_dir=self.tmp / "d")
        try:
            ui = PrinterService(ctx.db, ctx.events, [self.backend(["Laser Sala", "Rede Usuario"], "Laser Sala")],
                                ctx.settings.get)
            ui.refresh()
            svc = PrinterService(ctx.db, ctx.events, [self.backend(["Laser Sala"])], ctx.settings.get, role="service")
            svc.refresh()
            recs = {p.name: p for p in svc.list()}
            self.assertTrue(recs["Laser Sala"].is_default)            # visão do usuário preservada
            self.assertTrue(recs["Laser Sala"].service_visible)
            self.assertFalse(recs["Rede Usuario"].service_visible)
            self.assertTrue(recs["Rede Usuario"].available)
            self.assertEqual(svc.resolve(None), "Laser Sala")
            ui.refresh()                                               # a interface não apaga a marca do serviço
            self.assertFalse({p.name: p for p in ui.list()}["Rede Usuario"].service_visible)
        finally:
            ctx.close()
