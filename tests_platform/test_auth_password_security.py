"""Regressões da auditoria A04 (29/10/2026): troca de senha.

A04-002: com o segundo fator pendente, quem só sabia a senha conseguia trocá-la e derrubar as sessões do dono.
A04-003: senha atual errada na troca não era registrada (rollback) nem contava para o bloqueio."""

import unittest

from tests_platform.support import ADMIN_PW
from tests_platform import test_api as ta
from tests_platform.test_api import setUpModule  # noqa: F401


class PasswordSecurity(ta.Api):
    locals().update({n: None for n in dir(ta.Api) if n.startswith("test_")})   # só a preparação da classe base

    def test_a04_002_no_password_change_before_second_factor(self):
        from fastapi.testclient import TestClient
        from vyonix.auth import totp
        c, _ = self.login()
        sec = c.post("/api/v1/auth/mfa/enroll").json()["secret"]
        self.assertEqual(c.post("/api/v1/auth/mfa/confirm",
                                json={"code": totp.code_at(sec, totp.current_step())}).status_code, 200)
        x = TestClient(self.app)                                  # só conhece a senha
        r = x.post("/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PW})
        self.assertEqual(r.json()["stage"], "mfa_verify")
        x.headers["X-CSRF-Token"] = r.json()["csrf"]
        r = x.post("/api/v1/auth/password", json={"current": ADMIN_PW, "new": "Senha-Do-Atacante-1"})
        self.assertNotEqual(r.status_code, 200, r.text)
        self.assertEqual(c.get("/api/v1/auth/me").status_code, 200)        # sessão legítima intacta

    def test_a04_003_wrong_current_password_is_recorded_and_locks(self):
        from tests_platform.support import require_db
        from vyonix.audit import service as audit
        c, _ = self.login()
        codes = [c.post("/api/v1/auth/password", json={"current": f"errada-{i}", "new": "Outra-Senha-123"}).status_code
                 for i in range(12)]
        self.assertTrue(all(x in (401, 403) for x in codes), codes)
        with require_db().session(self.t) as s:
            n = len(audit.query(s, action="auth.password_change_failed"))
        self.assertGreater(n, 0, "falhas não registradas na auditoria")
        # bloqueio (política padrão): depois de várias falhas a conta é bloqueada e a sessão encerrada
        self.assertEqual(c.get("/api/v1/auth/me").status_code, 401)
        from fastapi.testclient import TestClient
        r = TestClient(self.app).post("/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PW})
        self.assertEqual(r.status_code, 401, "conta deveria estar bloqueada temporariamente")


if __name__ == "__main__":
    unittest.main()
