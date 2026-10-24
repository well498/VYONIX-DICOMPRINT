"""License Manager: recuperação do administrador pela frase-senha da chave de emissão (senha provisória em TXT)."""

import unittest

try:
    import cryptography  # noqa: F401
    HAS = True
except ImportError:
    HAS = False

from tests.helpers import TempDirTestCase


@unittest.skipUnless(HAS, "cryptography não instalado")
class LMRecoveryTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        from tests.licensing_support import PASS, make_manager
        self.PASS = PASS
        self.lm, self.admin, _keys, self.cid = make_manager(self.tmp / "lm")

    def tearDown(self):
        self.lm.close()
        super().tearDown()

    def test_recover_writes_provisional_password(self):
        from license_manager.security import AuthError
        with self.assertRaises(AuthError):
            self.lm.login("admin", "esqueci-a-senha")
        pw, path = self.lm.recover_admin("admin", self.PASS)
        self.assertTrue(path.is_file())
        self.assertEqual(path.parent, self.lm.paths.root)
        text = path.read_text(encoding="utf-8-sig")
        self.assertIn("Usuário: admin", text)
        self.assertIn(f"Senha provisória: {pw}", text)
        user = self.lm.login("admin", pw)
        self.assertTrue(user.must_change)                 # obriga a troca
        with self.assertRaises(AuthError):
            self.lm.login("admin", "Senha-Forte-123")      # a senha antiga deixou de valer
        self.lm.change_password(user, pw, "Nova-Senha-456")
        self.assertFalse(self.lm.login("admin", "Nova-Senha-456").must_change)
        # dados preservados
        self.assertEqual(self.lm.customer(self.cid)["name"], "Clínica Teste Ltda")
        actions = [a["action"] for a in self.lm.audit_log()]
        self.assertIn("user.recover_admin", actions)
        self.assertEqual(self.lm.verify_audit(), [])
        self.assertNotIn(self.PASS, path.read_text(encoding="utf-8-sig"))   # a frase-senha nunca vai para o TXT

    def test_blank_username_uses_first_admin(self):
        pw, path = self.lm.recover_admin("", self.PASS)
        self.assertIn("Usuário: admin", path.read_text(encoding="utf-8-sig"))
        self.lm.login("admin", pw)

    def test_wrong_passphrase_and_lockout(self):
        from license_manager.security import AuthError
        for _ in range(4):
            with self.assertRaises(AuthError):
                self.lm.recover_admin("admin", "frase-errada-123")
        with self.assertRaisesRegex(AuthError, "bloqueada por 15 minutos"):
            self.lm.recover_admin("admin", "frase-errada-123")
        with self.assertRaisesRegex(AuthError, "bloqueada temporariamente"):
            self.lm.recover_admin("admin", self.PASS)    # nem a frase certa passa durante o bloqueio
        self.lm.login("admin", "Senha-Forte-123")         # a senha original continua válida
        self.assertEqual(list(self.lm.paths.root.glob("VYONIX_LM_senha_provisoria_*.txt")), [])

    def test_only_admins_can_be_recovered(self):
        from license_manager.security import AuthError
        self.lm.create_user(self.admin, "consulta", "Consulta", "viewer", "Senha-Viewer-789")
        with self.assertRaises(AuthError):
            self.lm.recover_admin("consulta", self.PASS)

    def test_without_signing_key_there_is_no_recovery(self):
        from license_manager.paths import LMPaths
        from license_manager.service import LicenseManager, LMError
        lm2 = LicenseManager(LMPaths(self.tmp / "vazio", "custom"))
        try:
            lm2.initialize("admin", "Administrador", "Senha-Forte-123")
            with self.assertRaises(LMError):
                lm2.recover_admin("admin", self.PASS)
        finally:
            lm2.close()


if __name__ == "__main__":
    unittest.main()


try:
    from app.ui import qt as _qt  # noqa: F401
    HAS_QT = True
except ImportError:
    HAS_QT = False


@unittest.skipUnless(HAS and HAS_QT, "PySide6 não instalado")
class LMRecoveryUiTest(TempDirTestCase):
    def test_login_dialog_forgot_password(self):
        import os
        from unittest import mock
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from app.ui.qt import QApplication
        _app = QApplication.instance() or QApplication([])
        from license_manager.ui import dialogs
        from tests.licensing_support import PASS, make_manager
        lm, _admin, _k, _c = make_manager(self.tmp / "lm")
        try:
            dlg = dialogs.LoginDialog(lm)
            texts = [b.text() for b in dlg.findChildren(dialogs.QPushButton)] if hasattr(dialogs, "QPushButton") else []
            msgs = []
            with mock.patch.object(dialogs, "info", lambda *a, **k: msgs.append(a[1])), \
                    mock.patch.object(dialogs, "error", lambda *a, **k: msgs.append(str(a[1]))), \
                    mock.patch("os.startfile", create=True):
                dlg.username.setText("admin")
                self.assertIsNone(dlg.recover(passphrase="errada-errada-1"))
                path = dlg.recover(passphrase=PASS)
            self.assertIsNotNone(path)
            self.assertIn("Senha provisória gravada em", msgs[-1])
            if texts:
                self.assertIn("Esqueci a senha…", texts)
        finally:
            lm.close()
