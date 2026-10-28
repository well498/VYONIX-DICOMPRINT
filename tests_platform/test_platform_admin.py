"""Administração global VYONIX (Prompt Mestre §4, §16): operadora cadastra instituições pelo assistente (dados,
módulos contratados, estrutura, administrador inicial com senha provisória), lista só dados administrativos,
desativa e reativa (sessões encerradas, login bloqueado, nada apagado); instituições não acessam a administração
global; a operadora não vê dados clínicos. Modo cloud, API real, PostgreSQL real; dados fictícios."""

from __future__ import annotations

import secrets
import shutil
import tempfile
import unittest
from pathlib import Path

from tests_platform.support import ADMIN_PW, require_db

NEW = "Senha-Definitiva-2026!"


def setUpModule():
    global db
    db = require_db()


def cnpj(base12: str) -> str:
    def dv(b, w):
        r = sum(int(a) * c for a, c in zip(b, w)) % 11
        return "0" if r < 2 else str(11 - r)
    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    d1 = dv(base12, w1)
    return base12 + d1 + dv(base12 + d1, [6] + w1)


class PlatformAdmin(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from tests.licensing_support import Computer
        from tests_platform.test_licensing import Base
        from vyonix.api.app import create_app
        from vyonix.config import Config
        from vyonix.context import build
        from vyonix.tenancy import platform_admin
        self.tmp = Path(tempfile.mkdtemp(prefix="vyx-op-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sfx = secrets.token_hex(3)
        self.op_login = f"admin.geral.{self.sfx}"
        self.op_id = platform_admin.create_operator(db, code=f"vyonix-{self.sfx}", name="VYONIX (teste)",
                                                    admin_username=self.op_login, admin_password=ADMIN_PW)
        h = Base.__new__(Base)
        h.keys = {}
        cfg = Config(data_dir=self.tmp / "data", mode="cloud")
        self.app = create_app(build(cfg, licensing=h.licensing(Computer()), db=db), cookie_secure=False)
        self.TestClient = TestClient

    def login(self, user, pw=ADMIN_PW, expect=200):
        c = self.TestClient(self.app)
        r = c.post("/api/v1/auth/login", json={"username": user, "password": pw})
        self.assertEqual(r.status_code, expect, r.text)
        if expect == 200:
            c.headers["X-CSRF-Token"] = r.json()["csrf"]
        return c, r

    def wizard(self, op, **kw):
        body = {"code": f"alfa-{self.sfx}", "name": "Clínica Alfa", "legal_name": "Clínica Alfa Ltda (fictícia)",
                "document": cnpj("112223330001"), "institution_type": "clinica",
                "sites": ["Unidade Centro", "Unidade Norte"], "modules": ["pacs", "report"], "structure": "cdi",
                "admin_login": f"gestor.alfa.{self.sfx}", "admin_name": "Gestora Alfa",
                "admin_password": "Provisoria-2026x", "contact_email": "contato@alfa.example", **kw}
        return op.post("/api/v1/platform/institutions", json=body)

    def test_wizard_listing_and_limits(self):
        op, r = self.login(self.op_login)
        self.assertEqual(r.json()["organization"]["kind"], "operator")
        for bad in ({"document": "11.222.333/0001-00"}, {"institution_type": "padaria"}, {"structure": "x"},
                    {"modules": ["pacs", "foguete"]}, {"sites": ["A", "a"]}):
            self.assertEqual(self.wizard(op, **bad).status_code, 422, bad)
        r = self.wizard(op)
        self.assertEqual(r.status_code, 201, r.text)
        tid = r.json()["id"]
        self.assertEqual(self.wizard(op, code=f"alfa2-{self.sfx}").json()["error"], "login_taken")
        items = op.get("/api/v1/platform/institutions").json()["items"]
        alfa = next(x for x in items if x["id"] == tid)
        self.assertEqual((alfa["sites"], alfa["users"], alfa["contracted_modules"], alfa["institution_type"]),
                         (2, 1, ["pacs", "report"], "clinica"))
        self.assertEqual(alfa["document"], cnpj("112223330001"))
        self.assertNotIn(str(self.op_id), [x["id"] for x in items])               # a operadora não é instituição
        self.assertFalse(set(alfa) & {"patients", "studies", "reports"})
        # gestor inicial: senha provisória com troca obrigatória, entra só com usuário e senha
        g, r = self.login(f"gestor.alfa.{self.sfx}", "Provisoria-2026x")
        self.assertEqual((r.json()["stage"], r.json()["tenant_id"]), ("password_change", tid))
        g.post("/api/v1/auth/password", json={"current": "Provisoria-2026x", "new": NEW})
        g, r = self.login(f"gestor.alfa.{self.sfx}", NEW)
        self.assertEqual(r.json()["organization"]["kind"], "institution")
        self.assertIn("coordenador_cdi", [x["code"] for x in g.get("/api/v1/roles").json()])   # estrutura CDI
        self.assertEqual(len(g.get("/api/v1/sites").json()), 2)
        # o gestor (papel administrador, todas as permissões) não acessa a administração global
        r = g.get("/api/v1/platform/institutions")
        self.assertEqual((r.status_code, r.json()["error"]), (403, "operator_only"))
        # a operadora não vê dados clínicos da instituição
        pat = g.post("/api/v1/patients", json={"name": "Paciente Ficticia Alfa", "birth_date": "1980-01-01",
                                               "sex": "F", "identifiers": [{"issuer": "LOCAL", "value": "A1"}]})
        self.assertEqual(pat.status_code, 201, pat.text)
        self.assertNotIn("Paciente Ficticia Alfa", op.get("/api/v1/patients", params={"q": "Ficticia"}).text)

    def test_deactivate_blocks_access_without_deleting(self):
        op, _ = self.login(self.op_login)
        tid = self.wizard(op).json()["id"]
        g, _ = self.login(f"gestor.alfa.{self.sfx}", "Provisoria-2026x")
        g.post("/api/v1/auth/password", json={"current": "Provisoria-2026x", "new": NEW})
        g, _ = self.login(f"gestor.alfa.{self.sfx}", NEW)
        self.assertEqual(g.get("/api/v1/users").status_code, 200)
        u = f"/api/v1/platform/institutions/{tid}"
        self.assertEqual(op.patch(u, json={"active": False}).status_code, 422)          # motivo obrigatório
        self.assertEqual(op.patch(u, json={"active": False, "reason": "Contrato encerrado (teste)"}).status_code, 200)
        self.assertEqual(g.get("/api/v1/users").status_code, 401)                       # sessão encerrada
        self.login(f"gestor.alfa.{self.sfx}", NEW, expect=401)                           # acesso bloqueado
        item = next(x for x in op.get("/api/v1/platform/institutions").json()["items"] if x["id"] == tid)
        self.assertEqual((item["active"], item["users"]), (False, 1))                   # nada apagado
        g, _ = self.login(self.op_login)
        self.assertEqual(op.patch(u, json={"active": True}).status_code, 200)
        g, _ = self.login(f"gestor.alfa.{self.sfx}", NEW)
        self.assertEqual(g.get("/api/v1/users").status_code, 200)
        from vyonix.audit import service as audit
        with db.session(self.op_id) as s:
            acts = [e.action for e in audit.query(s, action="platform.*")]
        self.assertEqual(sorted(acts), ["platform.institution.active", "platform.institution.active",
                                        "platform.institution.create"])
        # outra instituição não consegue desativar ninguém
        self.assertEqual(g.patch(u, json={"active": False, "reason": "x"}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
