"""Interface do VYONIX License Manager com o Qt real (offscreen): janela, páginas e diálogos."""

import os
import unittest

try:
    import PySide6  # noqa: F401
    HAS_QT = True
except ImportError:
    HAS_QT = False

from tests.helpers import TempDirTestCase


@unittest.skipUnless(HAS_QT, "PySide6 não instalado")
class LicenseManagerUiTest(TempDirTestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_window_pages_and_dialogs(self):
        from vyonix_protocol import formats as F
        from license_manager.ui.dialogs import (CustomerDialog, IssueDialog, LoginDialog, ReactivateDialog,
                                                RenewDialog, SetupDialog)
        import license_manager.ui.main as M
        from license_manager.ui.main import MainWindow

        def fail(parent, exc, title=None):          # um erro na página não pode abrir caixa modal no teste
            raise AssertionError(str(exc))
        orig = M.error
        M.error = fail
        self.addCleanup(setattr, M, "error", orig)
        from tests.licensing_support import Client, Computer, make_manager
        lm, admin, keys, cid = make_manager(self.tmp / "lm")
        self.addCleanup(lm.close)
        client = Client(Computer(), self.tmp / "c", keys)
        self.addCleanup(client.close)
        info = lm.import_request(admin, client.svc.request_code())
        lic = lm.issue(admin, info.request_id, cid, ltype="annual", edition="Profissional")
        w = MainWindow(lm, admin)
        for i, (label, page) in enumerate(w.pages):
            w.go(i)
            self.app.processEvents()
        self.assertEqual([lbl for lbl, _ in w.pages][4], "Licenças")
        lic_page = w.pages[4][1]
        self.assertGreaterEqual(lic_page.t.rowCount(), 1)
        dlg = IssueDialog(lm, admin, lm.import_request(admin, client.svc.request_code()), w)
        self.assertGreater(dlg.customer.count(), 1)
        v = dlg.validity.values()
        self.assertEqual(v["ltype"], "annual")
        dlg.validity.type.setCurrentIndex(dlg.validity.type.findData("permanent"))
        self.assertIn("Sem vencimento", dlg.validity.preview.text())
        RenewDialog(lm, admin, lic, w)
        from license_manager.ui.dialogs import ModulesBox, ModulesDialog
        mb = ModulesBox(requested=["core", "ris"], demo_days=15)
        vals = mb.values()
        self.assertEqual((vals["core"]["kind"], vals["ris"]["kind"], vals["ris"]["days"]), ("contract", "demo", 15))
        self.assertNotIn("print", vals)
        self.assertIsNone(ModulesBox().values())                 # desmarcado = licença v2
        ModulesDialog(lm, admin, lic, w)
        ReactivateDialog(lm, admin, lic, w)
        CustomerDialog(lm, admin, cid, w)
        LoginDialog(lm, w)
        from license_manager.paths import LMPaths
        from license_manager.service import LicenseManager
        fresh = LicenseManager(LMPaths(self.tmp / "novo", "custom"))
        self.addCleanup(fresh.close)
        SetupDialog(fresh, w)
        self.assertIn(F.PRODUCT_ID, [p["product_id"] for p in lm.products()])
        w.close()

    def test_commercial_page_actions(self):
        from license_manager.ui import commercial_page as CP
        from license_manager.ui.main import MainWindow

        def fail(parent, exc, title=None):
            raise AssertionError(str(exc))
        orig = CP.error
        CP.error = fail
        self.addCleanup(setattr, CP, "error", orig)
        CP.info = lambda *a, **k: None
        from tests.licensing_support import Client, Computer, make_manager
        lm, admin, keys, cid = make_manager(self.tmp / "lm")
        self.addCleanup(lm.close)
        client = Client(Computer(), self.tmp / "c", keys)
        self.addCleanup(client.close)
        info = lm.import_request(admin, client.svc.request_code())
        lic = lm.issue(admin, info.request_id, cid, ltype="monthly", edition="Profissional", price_cents=49900)
        w = MainWindow(lm, admin)
        idx = w.page_index("Gestão Comercial")
        w.go(idx)
        page = w.pages[idx][1]
        self.assertEqual(page.t.rowCount(), 1)
        self.assertEqual(page.t.item(0, 4).text(), "R$ 499,00")
        self.assertEqual(page.kpi["active"].text(), "1")
        page.t.selectRow(0)
        page.show_detail()
        self.assertGreaterEqual(page.tab_tables["history"].rowCount(), 1)
        for name in CP.ACTION_TITLES:
            CP.ActionDialog(page, page.rows[0], name)
        dlg = CP.ActionDialog(page, page.rows[0], "payment")
        dlg.w["reference"].setText("BOLETO-0001")
        dlg._ok()
        r = page.backend.action(page.rows[0]["id"], "payment", dlg.data)
        self.assertFalse(r["duplicate"])
        self.assertGreater(lm.commercial.subscription(lic["license_id"])["paid_until"], lic["expires_at"])
        pol = CP.PolicyDialog(page)
        pol.sp["grace_days"].setValue(10)
        pol._ok()
        self.assertEqual(lm.commercial.settings()["grace_days"], "10")
        CP.ConnectDialog(page)
        page.refresh()
        w.close()


if __name__ == "__main__":
    unittest.main()
