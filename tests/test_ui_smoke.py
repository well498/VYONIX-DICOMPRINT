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
            self.assertEqual(w.nav.count(), 13)
            self.assertEqual(len(MENU), 13)
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

    def test_print_and_rules_dialogs(self):
        """Diálogos das Fases 4 a 6 com o Qt real: perfis, regras e simulação."""
        from app.bootstrap import bootstrap
        from app.printing.profiles import PrintProfile
        from app.rules.engine import Rule
        from app.ui.pages.profiles_page import ProfileDialog
        from app.ui.pages.rules_page import RuleDialog, SimulationDialog
        from app.ui.qt import QWidget

        ctx = bootstrap(data_dir=self.tmp / "dlg")
        try:
            ctx.printers.refresh()
            parent = QWidget()
            pd = ProfileDialog(parent, ctx.profiles, None)
            pd.name.setText("Perfil UI")
            pd.layout_box.setCurrentIndex(pd.layout_box.findData("2x2"))
            pd.copies.setValue(2)
            pd._save()
            self.assertEqual(pd.error.text(), "")
            prof = ctx.profiles.list()[0]
            self.assertEqual((prof.layout, prof.copies, prof.margins), ("2x2", 2, None))
            pd2 = ProfileDialog(parent, ctx.profiles, prof)
            self.assertEqual(pd2._collect().layout, "2x2")

            rd = RuleDialog(parent, ctx, None)
            rd.name.setText("Regra UI")
            rd._add_condition({"field": "modality", "op": "eq", "value": "CT"})
            chk, w = rd.actions["copies"]
            chk.setChecked(True)
            w.setValue(3)
            chk, w = rd.actions["profile_id"]
            chk.setChecked(True)
            rd._save()
            self.assertEqual(rd.error.text(), "")
            rule = ctx.rules.list()[0]
            self.assertEqual(rule.actions, {"copies": 3, "profile_id": prof.id})
            self.assertEqual(RuleDialog(parent, ctx, rule).collect().conditions, rule.conditions)

            sim = SimulationDialog(parent, ctx)
            sim.modality.setText("CT")
            sim.simulate()
            text = sim.explanation.toPlainText()
            self.assertIn("Regra UI", text)
            self.assertGreater(sim.result.rowCount(), 5)
            parent.deleteLater()
        finally:
            ctx.close()

    def test_device_calibration_dialog_real_qt(self):
        """Calibração de imagem: setas ±0,5, campo, barra, pré-visualização assíncrona, folha 3 × 3 e escolha."""
        import time
        from app.bootstrap import bootstrap
        from app.printing.backends.pdf import PDF_PRINTER
        from app.ui.pages.device_calibration import DeviceCalibrationDialog
        from app.ui.pages.device_settings_dialog import DeviceSettingsDialog
        from app.ui.pages.identity_widgets import BackupBox, IdentityBox
        from app.ui.qt import QWidget
        from app.ui.workers import wait_all
        ctx = bootstrap(data_dir=self.tmp / "cal")
        try:
            ctx.printers.refresh()
            ctx.settings.update({"printing.default_printer": PDF_PRINTER}, actor="t")
            d = ctx.devices.create({"name": "Philips Brilliance 16", "ae_title": "CT_P", "modality": "CT"}, actor="t")
            parent = QWidget()
            dlg = DeviceCalibrationDialog(parent, ctx, d.id)
            b = dlg.controls["brightness"]
            b.up.click()
            b.up.click()
            self.assertEqual(b.value(), 1.0)
            dlg.controls["gamma"].down.click()
            self.assertEqual(dlg.controls["gamma"].value(), -0.5)
            dlg.controls["contrast"].slider.setValue(15)
            self.assertEqual(dlg.controls["contrast"].value(), 1.5)
            dlg.controls["contrast"].spin.setValue(1.7)
            self.assertEqual(dlg.controls["contrast"].value(), 1.7)
            self.assertTrue(b.is_dirty())
            self.assertIn("não salvas", dlg.dirty.text())
            end = time.monotonic() + 15
            while dlg._adjusted is None and time.monotonic() < end:
                wait_all(200)
                self.app.processEvents()
            self.assertIsNotNone(dlg._adjusted)
            self.assertIsNotNone(dlg._original)
            dlg.printer.setCurrentIndex(dlg.printer.findData(PDF_PRINTER))
            dlg.print_sheet()
            self.assertIsNotNone(dlg.last_round)
            dlg.best.setValue(1)
            dlg.apply_choice()
            chosen = dlg.current()
            ctx.device_settings.save_tone(d.id, chosen, actor="t", reason="teste")
            self.assertEqual(ctx.device_settings.tone(d.id), chosen)
            sd = DeviceSettingsDialog(parent, ctx, d)
            sd.editors["paper"].setCurrentIndex(sd.editors["paper"].findData("A3"))
            sd.editors["layout"].setCurrentIndex(sd.editors["layout"].findData("3x3"))
            sd.editors["header_enabled"].setCurrentIndex(sd.editors["header_enabled"].findData(True))
            values = sd.values()
            self.assertEqual((values["paper"], values["layout"], values["header_enabled"]), ("A3", "3x3", True))
            self.assertIsNone(values["margin_mm"])
            self.assertEqual(values["gamma"], chosen.gamma)       # calibração preservada ao salvar o formulário
            ib = IdentityBox(ctx)
            ib.refresh()
            BackupBox(ctx).refresh()
            dlg.timer.stop()
            wait_all(5000)
            parent.deleteLater()
        finally:
            ctx.close()

    def test_license_page_and_activation_screen_real_qt(self):
        """Tela inicial de ativação (4 botões) e página Licença com o Qt real e a política ativa."""
        from app.bootstrap import bootstrap
        from app.ui.pages.license_page import ActivationDialog, LicensePage
        from app.ui.workers import wait_all
        os.environ["VYONIX_LICENSE_ENFORCE"] = "1"
        try:
            ctx = bootstrap(data_dir=self.tmp)
        finally:
            os.environ["VYONIX_LICENSE_ENFORCE"] = "0"
        try:
            self.assertTrue(ctx.license.enforced)
            dlg = ActivationDialog(ctx)
            texts = [b.text() for b in dlg.buttons.values()]
            self.assertEqual(texts, ["Iniciar demonstração de 5 dias", "Ativar licença comercial",
                                     "Exportar solicitação", "Visualizar Hardware ID"])
            self.assertTrue(dlg.buttons["demo"].isEnabled())
            ctx.license.start_demo(actor="teste")
            page = LicensePage(ctx)
            page.refresh()
            wait_all(5000)
            self.app.processEvents()
            self.assertIn("Demonstração", page.state.text())
            self.assertIn("VYXH-", page.ids.text())
            dlg2 = ActivationDialog(ctx)
            self.assertFalse(dlg2.buttons["demo"].isEnabled())
        finally:
            ctx.close()

    def test_license_page_subscription_card_real_qt(self):
        """Página Licença com licença comercial: situação da assinatura, histórico e autorização offline."""
        from app.bootstrap import bootstrap
        from app.ui.pages.license_page import LicensePage
        from app.ui.workers import wait_all
        from tests.licensing_support import make_manager
        os.environ["VYONIX_LICENSE_ENFORCE"] = "1"
        try:
            ctx = bootstrap(data_dir=self.tmp / "app")
        finally:
            os.environ["VYONIX_LICENSE_ENFORCE"] = "0"
        lm, admin, keys, cid = make_manager(self.tmp / "lm")
        try:
            ctx.license.public_keys = keys
            info = lm.import_request(admin, ctx.license.request_code())
            lic = lm.issue(admin, info.request_id, cid, ltype="monthly", edition="Profissional")
            ctx.license.install(lic["document"], actor="t")
            ctx.license.import_authorization(lm.offline_authorization(admin, lic["license_id"])["document"],
                                             actor="t")
            page = LicensePage(ctx)
            page.refresh()
            wait_all(5000)
            self.app.processEvents()
            self.assertIn("ATIVA", page.sub.text())
            self.assertIn("Offline", page.sub.text())
            self.assertGreaterEqual(page.shist.rowCount(), 1)
        finally:
            lm.close()
            ctx.close()

    def test_dicom_rule_dialog_and_reception_page_real_qt(self):
        """Adicionar Regra DICOM sem IP, impressão sob demanda, tela do técnico e página do Reception."""
        from app.bootstrap import bootstrap
        from app.ui.pages.devices_page import DestinationDialog, DeviceDialog
        from app.ui.pages.reception_page import ReceptionPage
        from app.ui.workers import wait_all
        ctx = bootstrap(data_dir=self.tmp)
        try:
            dlg = DeviceDialog(None, ctx.devices, ctx=ctx)
            dlg.editors["name"].setText("Tomografia 01")
            dlg.editors["called_ae"].setText("VYONIX_CT01")
            mode = dlg.print_editors["auto_print"]
            mode.setCurrentIndex(mode.findData(False))
            dlg.print_editors["brightness"].setValue(1.5)
            dlg._save()
            rule = dlg.result_device
            self.assertIsNotNone(rule)
            self.assertIsNone(rule.ip_address)
            self.assertEqual(rule.called_ae, "VYONIX_CT01")
            vals = ctx.device_settings.get(rule.id)
            self.assertFalse(vals["auto_print"])
            self.assertEqual(vals["brightness"], 1.5)
            dd = DestinationDialog(None, ctx, rule)
            self.assertEqual(dd.port, ctx.settings.get("dicom.storage.port"))
            page = ReceptionPage(ctx)
            page.refresh()
            wait_all(5000)
            self.app.processEvents()
            self.assertIn("https://", page.url.text())
        finally:
            ctx.close()

    def test_tray_and_close_to_tray(self):
        from app.bootstrap import bootstrap
        from app.ui.application import _make_tray
        from app.ui.main_window import MainWindow
        ctx = bootstrap(data_dir=self.tmp / "tray")
        try:
            w = MainWindow(ctx)
            tray = _make_tray(self.app, w, ctx)
            self.assertIn("VYONIX", tray.toolTip())
            w.hide_on_close = True
            w.show()
            w.close()
            self.assertFalse(w.isVisible())          # escondida, não encerrada
            w.bring_to_front()
            self.assertTrue(w.isVisible())
            w.quitting = True
            w.close()
            tray.hide()
            w.shutdown()
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
