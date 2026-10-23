"""Barra de operação (Pausar/Retomar sistema, Abrir log) e pausa segura em configurações sensíveis — Qt real."""

import os
import unittest

try:
    from app.ui import qt as _qt  # noqa: F401
    HAS_QT = True
except ImportError:
    HAS_QT = False

from tests.helpers import TempDirTestCase


@unittest.skipUnless(HAS_QT, "PySide6 não instalado")
class UiOperationTest(TempDirTestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from app.ui.qt import QApplication, prepare_application
        if QApplication.instance() is None:
            prepare_application()
        cls.app = QApplication.instance() or QApplication([])

    def test_pause_resume_and_log(self):
        from app.bootstrap import bootstrap
        from app.ui.main_window import MainWindow
        from app.ui.workers import wait_all
        ctx = bootstrap(data_dir=self.tmp)
        try:
            w = MainWindow(ctx)
            bar = w.operation_bar
            self.assertEqual(bar.toggle.text(), "Pausar sistema")
            self.assertTrue(bar.badge.isHidden())
            self.assertFalse(bar.pause_system(reason="  ", ask_admin=False))     # motivo obrigatório
            self.assertFalse(ctx.operation.state().paused)
            self.assertTrue(bar.pause_system(reason="Troca de papel", ask_admin=False))
            self.assertTrue(ctx.operation.state().paused)
            self.assertEqual(bar.toggle.text(), "Retomar sistema")
            self.assertFalse(bar.badge.isHidden())
            self.assertIn("Troca de papel", bar.badge.toolTip())
            self.assertTrue(bar.resume_system(confirm=False, ask_admin=False))
            self.assertFalse(ctx.operation.state().paused)
            self.assertEqual(bar.toggle.text(), "Pausar sistema")
            self.assertEqual(bar.log_folder(), ctx.log_file.parent)
            self.assertTrue(bar.log_folder().is_dir())
            w.shutdown()
            wait_all(5000)
        finally:
            ctx.close()

    def test_sensitive_settings_require_pause(self):
        from app.bootstrap import bootstrap
        from app.ui.pages.settings_page import SettingsPage
        ctx = bootstrap(data_dir=self.tmp / "s")
        try:
            page = SettingsPage(ctx.settings, ctx.paths.exports_dir, ctx.access, ctx=ctx)
            self.assertTrue(page.ensure_safe_pause({"site.name": "Unidade"}))          # não sensível
            self.assertFalse(ctx.operation.state().paused)
            changes = {"dicom.storage.port": 11200}
            self.assertEqual(page.sensitive_changes(changes), ["Porta TCP"])
            self.assertFalse(page.ensure_safe_pause(changes, answer=False))           # cancelado
            self.assertFalse(ctx.operation.state().paused)
            self.assertTrue(page.ensure_safe_pause(changes, answer=True))
            st = ctx.operation.state()
            self.assertTrue(st.paused)
            self.assertIn("Porta TCP", st.reason)
            self.assertTrue(page.ensure_safe_pause(changes))                          # já pausado
        finally:
            ctx.close()


if __name__ == "__main__":
    unittest.main()
