"""API HTTP do Core: cookie de sessão, CSRF, permissões por papel, erros e cabeçalhos de segurança."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from tests_platform.support import ADMIN_PW, new_org, require_db


def setUpModule():
    global db
    db = require_db()


class Api(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from tests.licensing_support import Computer, make_manager
        from tests_platform.test_licensing import Base
        from vyonix.api.app import create_app
        from vyonix.config import Config
        from vyonix.context import build
        self.tmp = Path(tempfile.mkdtemp(prefix="vyx-api-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.pc = Computer()
        self.lm, self.lm_admin, self.keys, self.cid = make_manager(self.tmp / "lm", clock=lambda: self.pc.clock.wall)
        self.addCleanup(self.lm.close)
        helper = Base.__new__(Base)
        helper.keys = self.keys
        lic = helper.licensing(self.pc)
        self.code = f"api-{self.id().split('.')[-1][:20].replace('_', '-')}"
        self.t = new_org(db, self.code)
        cfg = Config(data_dir=self.tmp / "data", default_organization=self.code)
        self.plat = build(cfg, licensing=lic, db=db)
        self.app = create_app(self.plat, cookie_secure=False)
        self.client = TestClient(self.app)

    def login(self, client=None, user="admin", pw=ADMIN_PW):
        from fastapi.testclient import TestClient
        c = client or TestClient(self.app)
        r = c.post("/api/v1/auth/login", json={"username": user, "password": pw})
        self.assertEqual(r.status_code, 200, r.text)
        c.headers["X-CSRF-Token"] = r.json()["csrf"]
        return c, r

    def test_login_cookie_flags_and_me(self):
        c, r = self.login()
        cookie = r.headers["set-cookie"].lower()
        for flag in ("httponly", "samesite=strict", "path=/"):
            self.assertIn(flag, cookie)
        self.assertNotIn("vyx_session", r.text)            # token não vai no corpo
        me = c.get("/api/v1/auth/me").json()
        self.assertEqual(me["username"], "admin")
        self.assertEqual(me["stage"], "ok")
        self.assertIn("core.users.manage", me["permissions"])

    def test_wrong_password_generic_and_lockout_persisted(self):
        for _ in range(5):
            r = self.client.post("/api/v1/auth/login", json={"username": "admin", "password": "errada"})
            self.assertEqual(r.status_code, 401)
            self.assertEqual(r.json()["message"], "Usuário ou senha inválidos.")
        r = self.client.post("/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PW})
        self.assertEqual(r.status_code, 401)                # bloqueado

    def test_csrf_required_for_changes(self):
        c, _ = self.login()
        token = c.headers.pop("X-CSRF-Token")
        r = c.post("/api/v1/sites", json={"name": "Filial"})
        self.assertEqual((r.status_code, r.json()["error"]), (403, "csrf"))
        c.headers["X-CSRF-Token"] = token
        r = c.put("/api/v1/settings/core/institution", json={"value": {"display_name": "Clínica X"}})
        self.assertEqual(r.status_code, 200, r.text)

    def test_unauthenticated_and_security_headers(self):
        r = self.client.get("/api/v1/users")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.headers["x-frame-options"], "DENY")
        self.assertIn("default-src 'self'", r.headers["content-security-policy"])
        self.assertEqual(r.headers["cache-control"], "no-store")
        h = self.client.get("/api/v1/health")
        self.assertEqual(h.json()["status"], "ok")

    def test_role_permissions(self):
        c, _ = self.login()
        r = c.post("/api/v1/users", json={"username": "recep", "display_name": "Recepção",
                                          "password": "Recepcao-1234", "roles": [{"role": "recepcionista"}]})
        self.assertEqual(r.status_code, 201, r.text)
        # a primeira entrada exige troca de senha
        rc, _ = self.login(user="recep", pw="Recepcao-1234")
        self.assertEqual(rc.get("/api/v1/patients").json()["details"]["stage"], "password_change")
        self.assertEqual(rc.post("/api/v1/auth/password", json={"current": "Recepcao-1234",
                                                                "new": "Recepcao-5678"}).status_code, 200)
        r = rc.post("/api/v1/patients", json={"name": "Paciente API", "identifiers": [{"issuer": "PRONT",
                                                                                         "value": "77"}]})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(rc.get("/api/v1/users").status_code, 403)
        self.assertEqual(rc.get("/api/v1/audit").status_code, 403)
        self.assertEqual(rc.post("/api/v1/patients/merge", json={"source_id": r.json()["id"],
                                                                 "target_id": r.json()["id"],
                                                                 "reason": "x x"}).status_code, 403)
        audit = c.get("/api/v1/audit?action=patient.*").json()
        self.assertEqual(audit[0]["actor"], "recep")
        self.assertTrue(c.get("/api/v1/audit/verify").json()["ok"])

    def test_platform_works_without_license(self):
        """Decisão de 04/11/2026: sem License Manager, Hardware ID, ativação ou limites de licença na plataforma."""
        c, _ = self.login()
        for i in range(4):                                                 # sem limite de unidades
            self.assertEqual(c.post("/api/v1/sites", json={"name": f"Unidade {i}"}).status_code, 201)
        for i in range(5):                                                 # sem limite de usuários
            r = c.post("/api/v1/users", json={"username": f"u{i}", "display_name": f"U {i}",
                                              "password": "Senha-Teste-1234", "roles": [{"role": "recepcionista"}]})
            self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(c.get("/api/v1/license").status_code, 404)        # rotas de licença retiradas
        self.assertIn(c.post("/api/v1/license/install", json={"document": "x"}).status_code, (404, 405))
        mods = {m["code"]: m for m in c.get("/api/v1/modules").json()}
        self.assertFalse(mods["notify"]["available"])                      # planejado
        for code in ("pacs", "ris", "report", "print"):                    # habilita por configuração
            self.assertEqual(c.post(f"/api/v1/modules/{code}/enable").status_code, 200, code)
        self.assertEqual(c.post("/api/v1/modules/notify/enable").status_code, 422)
        sysinfo = c.get("/api/v1/system").json()
        self.assertFalse(sysinfo["licensing"]["required"])
        self.assertEqual({m["code"]: m["status"] for m in sysinfo["modules"]}["pacs"], "enabled")
        self.assertIn("VYONIX DICOM Print", [p["name"] for p in sysinfo["separate_products"]])
        self.assertEqual(c.post("/api/v1/modules/pacs/disable", json={"reason": "teste"}).status_code, 200)
        self.assertNotEqual({m["code"]: m["status"] for m in c.get("/api/v1/modules").json()}["pacs"], "enabled")

    def test_validation_errors_are_structured(self):
        c, _ = self.login()
        r = c.post("/api/v1/patients", json={"name": "A", "sex": "Z"})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error"], "validation")
        self.assertTrue(any(e["field"] == "sex" for e in r.json()["details"]["errors"]))


if __name__ == "__main__":
    unittest.main()
