"""F1-09 — teste de fumaça da interface real. Requer PySide2 ou PySide6 (ignorado sem eles).

Executa com a plataforma Qt ``offscreen``, sem abrir janelas.
"""

import os
import unittest

try:
    from app.ui import qt as _qt  # noqa: F401
    HAS_QT = True
except ImportError:
    HAS_QT = False

from tests.helpers import TempDirTestCase


@unittest.skipUnless(HAS_QT, "PySide2/PySide6 não instalado")
class UiSmokeTest(TempDirTestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from app.ui.qt import QApplication, install_translations, prepare_application
        if QApplication.instance() is None:
            prepare_application()
        cls.app = QApplication.instance() or QApplication([])
        install_translations(cls.app)

    def test_main_window_pages(self):
        from app.bootstrap import bootstrap
        from app.ui import theme
        from app.ui.main_window import MENU, MainWindow
        from app.ui.workers import wait_all

        ctx = bootstrap(data_dir=self.tmp)
        try:
            self.assertIn(theme.apply_theme(self.app, "dark"), ("dark",))
            w = MainWindow(ctx)
            self.assertEqual(w.nav.count(), 12)
            self.assertEqual(len(MENU), 12)
            for row in range(w.nav.count()):
                w.nav.setCurrentRow(row)
                wait_all(5000)
                self.app.processEvents()
            sp = w.settings_page
            sp.editors["site.name"].setText("Unidade Teste")
            sp.save()
            wait_all(5000)
            self.app.processEvents()
            self.assertEqual(ctx.settings.get("site.name"), "Unidade Teste")
            w.shutdown()
            w.close()
        finally:
            ctx.close()

    def test_builtin_smoke_routine(self):
        import json
        from app.main import EXIT_OK, main

        report = self.tmp / "smoke.json"
        code = main(["--smoke-test", "--data-dir", str(self.tmp / "d"), "--report", str(report)])
        data = json.loads(report.read_text(encoding="utf-8"))
        failed = [c for c in data["checks"] if not c["ok"]]
        self.assertEqual(failed, [])
        self.assertEqual(code, EXIT_OK)


if __name__ == "__main__":
    unittest.main()
