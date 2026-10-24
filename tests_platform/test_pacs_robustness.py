"""PACS — permissões por papel, falha de comunicação com o motor, recuperação e persistência após reinício do Core.

Plataforma real (API, licenciamento, PostgreSQL com RLS) e o motor DUBLÊ DE TESTE ``MemoryBackend`` (com
interruptor de queda). Dados sintéticos.
"""

from __future__ import annotations

import unittest

from tests_platform.pacs_support import MemoryBackend, make_dicom, uid
from tests_platform.support import require_db
from tests_platform.test_pacs import ApiBase

DW = "/api/v1/pacs/dicomweb"


def setUpModule():
    global db
    db = require_db()
    from tests_platform import test_pacs
    test_pacs.db = db                       # ApiBase usa o banco do módulo de origem


class Roles(ApiBase):
    """Matriz de permissões (papéis padrão do manifesto): quem pesquisa, envia e administra o PACS."""

    def setUp(self):
        super().setUp()
        self.c = self.login()
        self.license_and_enable()
        body, ctype = self.stow_body(make_dicom())
        self.assertEqual(self.c.post(DW + "/studies", content=body, headers={"Content-Type": ctype}).status_code, 200)
        self.users = {"admin": self.c}
        for role in ("supervisor", "tecnico", "recepcionista"):
            r = self.c.post("/api/v1/users", json={"username": role, "display_name": role.title(),
                                                   "password": "Senha-Teste-1234", "roles": [{"role": role}]})
            self.assertEqual(r.status_code, 201, r.text)
            c = self.login(role, "Senha-Teste-1234")
            # usuário criado pelo administrador troca a senha no primeiro acesso (antes disso, nada é liberado)
            self.assertEqual(c.get(f"{DW}/studies").status_code, 403)
            r = c.post("/api/v1/auth/password", json={"current": "Senha-Teste-1234", "new": "Senha-Nova-9876!"})
            self.assertIn(r.status_code, (200, 204), r.text)
            self.users[role] = self.login(role, "Senha-Nova-9876!")

    def test_matrix(self):
        from fastapi.testclient import TestClient
        st, se, sop = uid(1), uid(1, 1), uid(1, 1, 1)
        reads = [("GET", f"{DW}/studies"), ("GET", f"{DW}/studies/{st}/metadata"),
                 ("GET", f"{DW}/studies/{st}/series/{se}/instances/{sop}"), ("GET", f"/api/v1/pacs/studies/{st}/quality")]
        admin_only = [("GET", "/api/v1/pacs/status"), ("GET", "/api/v1/pacs/routes"), ("GET", "/api/v1/pacs/nodes")]
        expect = {                                  # papel → (pesquisa/recupera, envia, administra)
            "admin": (True, True, True), "supervisor": (True, True, True),
            "tecnico": (True, True, False), "recepcionista": (False, False, False)}
        for role, (can_read, can_store, can_admin) in expect.items():
            c = self.users[role]
            for m, path in reads:
                code = c.request(m, path).status_code
                self.assertEqual(code in (200, 204), can_read, f"{role} {path}: {code}")
                if not can_read:
                    self.assertEqual(code, 403)
            for m, path in admin_only:
                code = c.request(m, path).status_code
                self.assertEqual(code == 200, can_admin, f"{role} {path}: {code}")
            body, ctype = self.stow_body(make_dicom(sop=uid(1, 1, 50 + len(role)), instance_number=50 + len(role)))
            code = c.post(DW + "/studies", content=body, headers={"Content-Type": ctype}).status_code
            self.assertEqual(code == 200, can_store, f"{role} STOW: {code}")
        anon = TestClient(self.client.app)
        for m, path in reads + admin_only:
            self.assertEqual(anon.request(m, path).status_code, 401, path)


class EngineOutage(ApiBase):
    def test_search_survives_retrieve_fails_clearly_and_recovers(self):
        self.c = self.login()
        self.license_and_enable()
        data = make_dicom()
        body, ctype = self.stow_body(data)
        self.assertEqual(self.c.post(DW + "/studies", content=body, headers={"Content-Type": ctype}).status_code, 200)
        self.b.down = True
        r = self.c.get(f"{DW}/studies")
        self.assertEqual(r.status_code, 200)                                  # pesquisa vem do índice
        for path in (f"{DW}/studies/{uid(1)}", f"{DW}/studies/{uid(1)}/metadata",
                     f"{DW}/studies/{uid(1)}/series/{uid(1, 1)}/instances/{uid(1, 1, 1)}/frames/1"):
            r = self.c.get(path)
            self.assertEqual((r.status_code, r.json()["error"]), (503, "unavailable"), path)
            self.assertNotIn("Traceback", r.text)
        body2, ctype2 = self.stow_body(make_dicom(sop=uid(1, 1, 2), instance_number=2))
        self.assertEqual(self.c.post(DW + "/studies", content=body2, headers={"Content-Type": ctype2}).status_code, 503)
        st = self.c.get("/api/v1/pacs/status").json()
        self.assertFalse(st["engine"]["reachable"])
        self.assertEqual(st["index"]["instances"], 1)                         # nada indexado na falha
        self.b.down = False
        r = self.c.get(f"{DW}/studies/{uid(1)}/series/{uid(1, 1)}/instances/{uid(1, 1, 1)}")
        self.assertEqual(self.parts(r), [data])                               # recuperação idêntica depois da volta
        self.assertEqual(self.c.post(DW + "/studies", content=body2, headers={"Content-Type": ctype2}).status_code, 200)

    def test_cloud_sync_does_not_advance_during_outage(self):
        from vyonix.pacs import service as pacs
        from vyonix.pacs.backend import BackendUnavailable
        import secrets
        aet = f"OUT_{secrets.token_hex(3).upper()}"
        self.b.name = f"mem-out-{aet[-6:].lower()}"
        with db.session(self.t) as s:
            pacs.add_route(s, aet, actor="admin")
        for i in (1, 2):
            self.b.receive_cstore(make_dicom(sop=uid(1, 1, i), instance_number=i), called_aet=aet)
        self.b.down = True
        with self.assertRaises(BackendUnavailable):
            pacs.cloud_sync(db, self.b, allowed=lambda s: True)
        self.b.down = False
        out = pacs.cloud_sync(db, self.b, allowed=lambda s: True)
        self.assertEqual(out["indexed"], 2)                                   # nada perdido na queda


class CoreRestart(ApiBase):
    def test_index_and_audit_persist_across_core_restart(self):
        """Um Core novo (outra instância da aplicação, mesmo banco e motor) encontra e entrega tudo o que já havia."""
        from fastapi.testclient import TestClient
        from vyonix.api.app import create_app
        from vyonix.audit import service as audit
        from vyonix.config import Config
        from vyonix.context import build
        self.c = self.login()
        self.license_and_enable()
        data = make_dicom()
        body, ctype = self.stow_body(data)
        self.c.post(DW + "/studies", content=body, headers={"Content-Type": ctype})
        cfg = Config(data_dir=self.tmp / "data2", default_organization=self.code)
        plat2 = build(cfg, licensing=self.lic, db=db)
        plat2.options["pacs_backend"] = self.b
        self.client = TestClient(create_app(plat2, cookie_secure=False))    # "reinício" do Core
        c2 = self.login()
        self.assertEqual(c2.get(f"{DW}/studies").json()[0]["0020000D"]["Value"], [uid(1)])
        r = c2.get(f"{DW}/studies/{uid(1)}/series/{uid(1, 1)}/instances/{uid(1, 1, 1)}")
        self.assertEqual(self.parts(r), [data])
        with db.session(self.t) as s:
            self.assertEqual(len(audit.query(s, action="pacs.instance.store")), 1)
            self.assertEqual(audit.verify(s), [])                            # cadeia da auditoria íntegra


if __name__ == "__main__":
    unittest.main()
