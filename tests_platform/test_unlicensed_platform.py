"""Plataforma sem licença (decisão do proprietário de 04/11/2026), PostgreSQL real e dados sintéticos.

A plataforma é montada SEM o componente de licenciamento (``plat.licensing is None``): qualquer dependência
restante de licença quebraria estes testes. Cobre PACS, RIS, Viewer, Laudos/Telelaudos, administração e tarefas
automáticas, e confirma que nada é lido ou gravado no cofre/pasta de licenciamento compartilhados com o DICOM Print.
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from tests_platform.pacs_support import MemoryBackend, make_dicom, uid
from tests_platform.support import new_org, require_db

PW, NEW = "Senha-Teste-1234", "Senha-Nova-9876!"


def setUpModule():
    global db
    db = require_db()


class UnlicensedPlatform(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from vyonix.api.app import create_app
        from vyonix.config import Config
        from vyonix.context import build
        self.tmp = Path(tempfile.mkdtemp(prefix="vyx-free-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.code = f"free-{self.id().split('.')[-1][:24].replace('_', '-')}"
        self.t = new_org(db, self.code)
        self.b = MemoryBackend()
        self.cfg = Config(data_dir=self.tmp / "data", default_organization=self.code)
        self.plat = build(self.cfg, db=db)                       # sem licenciamento
        self.plat.options["pacs_backend"] = self.b
        self.client = TestClient(create_app(self.plat, cookie_secure=False))

    def login(self, user="admin", pw=None):
        from tests_platform.test_pacs import ADMIN_PW
        r = self.client.post("/api/v1/auth/login", json={"username": user, "password": pw or ADMIN_PW})
        self.assertEqual(r.status_code, 200, r.text)
        self.client.headers["X-CSRF-Token"] = r.json()["csrf"]
        return self.client

    def test_no_licensing_component_and_no_shared_vault_access(self):
        self.assertIsNone(self.plat.licensing)
        self.assertFalse(self.cfg.licensing_state_dir.exists())   # nada criado/lido na pasta de licenciamento

    def test_modules_admin_pacs_ris_report_viewer_without_license(self):
        c = self.login()
        for code in ("pacs", "ris", "report"):
            self.assertEqual(c.post(f"/api/v1/modules/{code}/enable").status_code, 200, code)
        for i in range(4):
            self.assertEqual(c.post("/api/v1/sites", json={"name": f"Unidade {i}"}).status_code, 201)
        self.assertEqual(c.get("/api/v1/system").json()["licensing"]["required"], False)
        # PACS: imagens recebidas e consultadas
        from vyonix.pacs import service as pacs
        with db.session(self.t) as s:
            for i in (1, 2):
                pacs.ingest(s, self.b, make_dicom(sop=uid(1, 1, i), instance_number=i), actor="pacs-sync", via="dimse")
        r = c.get("/api/v1/pacs/dicomweb/studies")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json())
        self.assertEqual(c.get("/api/v1/pacs/quality").status_code, 200)
        # Viewer (metadados para o visualizador web)
        self.assertEqual(c.get(f"/api/v1/pacs/dicomweb/studies/{uid(1)}/metadata").status_code, 200)
        # RIS: fila de preparação do técnico
        self.assertEqual(c.get("/api/v1/ris/prep").status_code, 200)
        # Laudos / Telelaudos: fila e abertura de laudo
        from vyonix.clinical import service as clinical
        with db.session(self.t) as s:
            st = clinical.register_study(s, study_instance_uid=uid(9), modality="CR", study_date=date(2026, 11, 4),
                                         actor="t")
            sid = str(st.id)
        self.assertEqual(c.get("/api/v1/report/worklist").status_code, 200)
        self.assertEqual(c.get("/api/v1/report/sla").status_code, 200)
        self.assertEqual(c.get("/api/v1/report/assignable-physicians").status_code, 200)
        r = c.post("/api/v1/report/reports", json={"study_id": sid})          # administrador: escopo de todas
        self.assertIn(r.status_code, (200, 201), r.text)                      # as unidades; laudo aberto sem licença

    def test_only_module_managers_enable_or_disable(self):
        """A07 (04/11): sem a barreira de licença, a permissão core.modules.manage é a única porta (403 por papel)."""
        from tests_platform.test_pacs import ADMIN_PW  # noqa: F401
        c = self.login()
        for role in ("recepcionista", "tecnico", "medico", "supervisor"):
            u = f"u_{role}"
            self.assertEqual(c.post("/api/v1/users", json={"username": u, "display_name": u, "password": PW,
                                                           "roles": [{"role": role}]}).status_code, 201)
        from fastapi.testclient import TestClient
        for role in ("recepcionista", "tecnico", "medico", "supervisor"):
            t = TestClient(self.client.app)
            r = t.post("/api/v1/auth/login", json={"username": f"u_{role}", "password": PW})
            t.headers["X-CSRF-Token"] = r.json()["csrf"]
            t.post("/api/v1/auth/password", json={"current": PW, "new": NEW})
            r = t.post("/api/v1/auth/login", json={"username": f"u_{role}", "password": NEW})
            t.headers["X-CSRF-Token"] = r.json()["csrf"]
            self.assertEqual(t.post("/api/v1/modules/pacs/enable").status_code, 403, role)
            self.assertEqual(t.post("/api/v1/modules/pacs/disable", json={"reason": "x"}).status_code, 403, role)

    def test_background_tasks_run_without_license(self):
        from vyonix.modules import registry
        from vyonix.pacs.sync_task import PacsSyncTask
        with db.session(self.t) as s:
            registry.enable(s, "pacs", actor="t")
        self.b.receive_cstore(make_dicom())
        out = PacsSyncTask(self.plat)()
        self.assertEqual(out.get("indexed"), 1, out)

    def test_monitoring_has_no_license_problem(self):
        c = self.login()
        h = c.get("/api/v1/health/detail").json()
        self.assertNotIn("license", h["components"])
        self.assertFalse(any("licen" in p.lower() for p in h["problems"]))


class SystemInfoExposure(unittest.TestCase):
    """A04 (04/11): /system no modo cloud não expõe dados do servidor compartilhado; mensagens sem caminhos."""

    def test_message_paths_are_masked(self):
        from vyonix.system_info import _clean
        m = _clean("Falha: C:\\ProgramData\\VYONIX\\Deploy\\x.log e /var/lib/vyonix/a/b.txt\nsegunda linha")
        self.assertNotIn("ProgramData", m)
        self.assertNotIn("/var/lib", m)
        self.assertNotIn("segunda", m)

    def test_cloud_tenant_does_not_see_server_wide_data(self):
        from types import SimpleNamespace
        from vyonix import system_info
        from vyonix.tenancy.models import Organization
        t = new_org(db, "free-cloud-sys")
        plat = SimpleNamespace(cfg=SimpleNamespace(mode="cloud", data_dir=Path("/nao/existe")))
        with db.session(t) as s:
            self.assertEqual(s.query(Organization).one().kind != "operator", True)
            self.assertFalse(system_info._server_wide_allowed(plat, s))
            ov = system_info.overview(plat, s)                    # rota inteira: sem dados do servidor
            self.assertFalse(ov["updates"]["available"])
            self.assertFalse(ov["backups"]["available"])
            self.assertNotIn("server_version", ov["database"])
        plat.cfg.mode = "edge"
        with db.session(t) as s:
            self.assertTrue(system_info._server_wide_allowed(plat, s))


if __name__ == "__main__":
    unittest.main()
