"""Política comercial no aplicativo completo: sem licença nem DEMO, as funções licenciadas ficam
suspensas (recepção recusada, fila parada) e voltam ao iniciar a demonstração — configurações preservadas."""

import os
import unittest

try:
    import pynetdicom  # noqa: F401
    HAS_NET = True
except ImportError:
    HAS_NET = False

from tests.helpers import TempDirTestCase


@unittest.skipUnless(HAS_NET, "pydicom/pynetdicom não instalados")
class EnforcementTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        from app.bootstrap import bootstrap
        from tests.dicom_helpers import free_port
        os.environ["VYONIX_LICENSE_ENFORCE"] = "1"
        self.addCleanup(os.environ.__setitem__, "VYONIX_LICENSE_ENFORCE", "0")
        self.port = free_port()
        self.ctx = bootstrap(data_dir=self.tmp / "data")
        self.addCleanup(self.ctx.close)
        self.ctx.settings.update({"dicom.storage.bind_address": "127.0.0.1", "dicom.storage.port": self.port},
                                 actor="t")
        self.ctx.storage_scp.start()
        dev = self.ctx.devices.create({"name": "CT", "ae_title": "CT_TESTE", "modality": "CT",
                                       "ip_address": "127.0.0.1"}, actor="t")
        self.ctx.devices.set_authorized(dev.id, True, actor="t")

    def test_suspended_then_demo(self):
        from app.dicom import scu
        lic = self.ctx.license
        self.assertTrue(lic.enforced)
        self.assertFalse(lic.allows("storage"))
        self.assertIsNotNone(self.ctx.worker.suspended())
        r = scu.echo("127.0.0.1", self.port, "VYONIX", calling_ae="CT_TESTE")
        self.assertFalse(r["ok"], r)
        self.assertIn("SUSPENSO", self.ctx.storage_scp.status().detail)
        import time
        from app.database.repositories.events_repo import EventFilter
        end = time.monotonic() + 5
        while time.monotonic() < end:          # o evento é gravado pela thread da associação, após a recusa
            actions = [e.action for e in self.ctx.events.query(EventFilter(limit=50))]
            if "assoc.unlicensed" in actions:
                break
            time.sleep(0.05)
        self.assertIn("assoc.unlicensed", actions)
        self.ctx.settings.update({"printing.copies": 2}, actor="t")
        lic.start_demo(actor="t")
        self.assertTrue(lic.allows("storage"))
        self.assertIsNone(self.ctx.worker.suspended())
        self.assertTrue(scu.echo("127.0.0.1", self.port, "VYONIX", calling_ae="CT_TESTE")["ok"])
        self.assertEqual(self.ctx.settings.get("printing.copies"), 2)
        self.assertIn("DEMONSTRAÇÃO", lic.mark_text())


if __name__ == "__main__":
    unittest.main()
