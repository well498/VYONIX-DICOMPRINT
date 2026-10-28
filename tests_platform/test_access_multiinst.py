"""Prompt Mestre — Fase 2: login só com usuário e senha no servidor com várias instituições (diretório global de
logins), contas independentes por instituição, delegação limitada de permissões, perfis opcionais e várias funções
na mesma conta. Servidor no modo cloud, API real, PostgreSQL real; instituições e pessoas fictícias."""

from __future__ import annotations

import secrets
import shutil
import tempfile
import unittest
from pathlib import Path

from tests_platform.support import ADMIN_PW, require_db

PW = "Senha-Provisoria-2026"
NEW = "Senha-Definitiva-2026!"


def setUpModule():
    global db
    db = require_db()


class MultiInstitution(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from tests.licensing_support import Computer
        from tests_platform.test_licensing import Base
        from vyonix.api.app import create_app
        from vyonix.config import Config
        from vyonix.context import build
        from vyonix.tenancy import service as tenancy
        self.tmp = Path(tempfile.mkdtemp(prefix="vyx-multi-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sfx = secrets.token_hex(3)
        self.adm = {k: f"gestor.{k}.{self.sfx}" for k in ("alfa", "beta", "gama")}
        self.org = {}
        for k, name in (("alfa", "Clínica Alfa"), ("beta", "Hospital Beta"), ("gama", "CDI Gama")):
            self.org[k] = tenancy.create_organization(db, code=f"{k}-{self.sfx}", name=name,
                                                      admin_username=self.adm[k], admin_password=ADMIN_PW,
                                                      register_login=True)
        h = Base.__new__(Base)
        h.keys = {}
        cfg = Config(data_dir=self.tmp / "data", mode="cloud")
        self.app = create_app(build(cfg, licensing=h.licensing(Computer()), db=db), cookie_secure=False)
        self.TestClient = TestClient

    def raw_login(self, user, pw, **extra):
        c = self.TestClient(self.app)
        r = c.post("/api/v1/auth/login", json={"username": user, "password": pw, **extra})
        if r.status_code == 200:
            c.headers["X-CSRF-Token"] = r.json()["csrf"]
        return c, r

    def login(self, user, pw=ADMIN_PW):
        c, r = self.raw_login(user, pw)
        self.assertEqual(r.status_code, 200, r.text)
        return c

    def staff(self, admin_client, username, roles, name="Pessoa Ficticia"):
        r = admin_client.post("/api/v1/users", json={"username": username, "display_name": name, "password": PW,
                                                     "roles": [{"role": x} for x in roles]})
        return r

    def first_login(self, username):
        c = self.login(username, PW)
        c.post("/api/v1/auth/password", json={"current": PW, "new": NEW})
        return self.login(username, NEW)

    def test_login_without_institution_and_independent_accounts(self):
        # cada gestor entra só com usuário e senha; o servidor identifica a instituição
        for k in ("alfa", "beta", "gama"):
            c, r = self.raw_login(self.adm[k].upper(), ADMIN_PW)                 # login sem diferenciar maiúsculas
            self.assertEqual((r.status_code, r.json()["tenant_id"]), (200, str(self.org[k])))
        # o mesmo médico nas duas instituições: logins diferentes, contas independentes
        alfa, beta = self.login(self.adm["alfa"]), self.login(self.adm["beta"])
        dr = f"dr.silva.{self.sfx}"
        self.assertTrue(alfa.get("/api/v1/users/login-available", params={"login": dr}).json()["available"])
        self.assertEqual(self.staff(alfa, dr, ["medico"]).status_code, 201)
        self.assertFalse(beta.get("/api/v1/users/login-available", params={"login": dr.upper()}).json()["available"])
        r = self.staff(beta, dr, ["medico"])
        self.assertEqual((r.status_code, r.json()["error"]), (409, "login_taken"))
        self.assertNotIn("Alfa", r.text)                                         # não revela onde está em uso
        self.assertEqual(self.staff(beta, f"silva.hbeta.{self.sfx}", ["medico"]).status_code, 201)
        a = self.first_login(dr)
        b = self.first_login(f"silva.hbeta.{self.sfx}")
        self.assertEqual(a.get("/api/v1/auth/me").json()["tenant_id"], str(self.org["alfa"]))
        self.assertEqual(b.get("/api/v1/auth/me").json()["tenant_id"], str(self.org["beta"]))
        # desativar na Alfa não afeta a conta da Beta
        uid = next(u["id"] for u in alfa.get("/api/v1/users").json() if u["username"] == dr)
        self.assertEqual(alfa.patch(f"/api/v1/users/{uid}", json={"active": False}).status_code, 200)
        self.assertEqual(self.raw_login(dr, NEW)[1].status_code, 401)
        self.assertEqual(self.raw_login(f"silva.hbeta.{self.sfx}", NEW)[1].status_code, 200)
        # a Beta não vê os usuários da Alfa
        self.assertNotIn(dr, [u["username"] for u in beta.get("/api/v1/users").json()])
        # mensagens genéricas: login desconhecido e senha errada são indistinguíveis
        r1 = self.raw_login(f"ninguem.{self.sfx}", "x")[1]
        r2 = self.raw_login(self.adm["gama"], "senha-errada")[1]
        self.assertEqual((r1.status_code, r2.status_code, r1.json()["message"]), (401, 401, r2.json()["message"]))

    def test_legacy_duplicate_logins_still_enter_with_organization(self):
        from tests_platform.support import new_org
        from vyonix.auth import directory
        t1, t2 = new_org(db, f"leg1-{self.sfx}"), new_org(db, f"leg2-{self.sfx}")       # "admin" nas duas, fora do diretório
        self.assertEqual(self.raw_login("admin", ADMIN_PW)[1].status_code, 401)
        c, r = self.raw_login("admin", ADMIN_PW, organization=f"leg2-{self.sfx}")
        self.assertEqual((r.status_code, r.json()["tenant_id"]), (200, str(t2)))
        with db.service_session() as s:
            self.assertIn("admin", [x["login"] for x in directory.conflicts(s)])
        del t1

    def test_delegation_cannot_escalate(self):
        alfa = self.login(self.adm["alfa"])
        r = alfa.put("/api/v1/roles/gestor_usuarios", json={"name": "Gestor de usuários",
                                                            "permissions": ["core.users.read", "core.users.manage"]})
        self.assertEqual(r.status_code, 200, r.text)
        g = f"gu.{self.sfx}"
        self.assertEqual(self.staff(alfa, g, ["gestor_usuarios"]).status_code, 201)
        gu = self.first_login(g)
        for roles in (["administrador"], ["medico"], ["recepcionista"]):        # papéis com permissões que não tem
            r = self.staff(gu, f"x{secrets.token_hex(3)}", roles)
            self.assertEqual((r.status_code, r.json()["error"]), (403, "cannot_delegate"), roles)
        self.assertEqual(self.staff(gu, f"ok.{self.sfx}", ["gestor_usuarios"]).status_code, 201)   # o que ele tem
        r = gu.put("/api/v1/roles/super", json={"name": "Super", "permissions": ["core.users.manage",
                                                                                 "core.settings.manage"]})
        self.assertEqual(r.status_code, 403)
        admin_id = next(u["id"] for u in gu.get("/api/v1/users").json() if u["username"] == self.adm["alfa"])
        for call in (lambda: gu.post(f"/api/v1/users/{admin_id}/reset-password", json={"password": "Outra-Senha-2026"}),
                     lambda: gu.patch(f"/api/v1/users/{admin_id}", json={"active": False}),
                     lambda: gu.put(f"/api/v1/users/{admin_id}/roles", json={"roles": [{"role": "gestor_usuarios"}]})):
            self.assertEqual(call().status_code, 403)                           # conta mais privilegiada: intocável
        self.assertEqual(self.raw_login(self.adm["alfa"], ADMIN_PW)[1].status_code, 200)
        # a escalada não cruza instituições: o administrador da Beta não enxerga o papel criado na Alfa
        beta = self.login(self.adm["beta"])
        self.assertNotIn("gestor_usuarios", [r["code"] for r in beta.get("/api/v1/roles").json()])

    def test_optional_profiles_and_multiple_functions(self):
        alfa = self.login(self.adm["alfa"])
        t = alfa.get("/api/v1/role-templates").json()
        self.assertEqual({x["code"] for x in t["templates"]},
                         {"coordenador_cdi", "gestor_telelaudos", "financeiro", "suporte_tecnico"})
        self.assertFalse(any(x["active"] for x in t["templates"]))               # nada é obrigatório
        self.assertNotIn("coordenador_cdi", [r["code"] for r in alfa.get("/api/v1/roles").json()])
        r = alfa.post("/api/v1/role-templates/structure/hospital")
        self.assertTrue(all(x["active"] for x in r.json()["templates"]))
        gama = self.login(self.adm["gama"])                                      # outra instituição: intacta
        self.assertFalse(any(x["active"] for x in gama.get("/api/v1/role-templates").json()["templates"]))
        self.assertEqual(gama.post("/api/v1/role-templates/coordenador_cdi/activate").json()["name"],
                         "Coordenador do CDI")
        # técnico que também coordena o CDI: um login, permissões somadas, sem liberar laudos
        tc = f"tecnico.coord.{self.sfx}"
        self.assertEqual(self.staff(gama, tc, ["tecnico", "coordenador_cdi"]).status_code, 201)
        me = self.first_login(tc).get("/api/v1/auth/me").json()
        perms = set(me["permissions"])
        self.assertTrue({"pacs.studies.store", "report.assign", "ris.schedule.manage"} <= perms)
        self.assertNotIn("report.sign", perms)
        self.assertEqual(sorted(r["role"] for r in me["roles"]), ["coordenador_cdi", "tecnico"])
        # o modelo ativado pode ser personalizado pelo gestor
        r = gama.put("/api/v1/roles/coordenador_cdi", json={"name": "Coordenação", "permissions": ["ris.schedule.read"]})
        self.assertEqual(r.status_code, 200, r.text)


if __name__ == "__main__":
    unittest.main()
