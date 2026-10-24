"""DEPLOY — ativação do módulo PACS: configuração gerada do Orthanc (sem plugins, REST só local e com senha
do cofre), configuração do Core preservada nos reparos, reversão das etapas e ordem do plano.
Arquivos reais numa pasta temporária; os passos de serviço e firewall do Windows são verificados no CI
Windows (aceitação do DEPLOY)."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from vyonix_deploy.config import DeployConfig
from vyonix_deploy.db import DeployDB
from vyonix_deploy.engine import Context
from vyonix_deploy.paths import default_paths


class PacsModuleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vyx-deploy-pacs-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.paths = default_paths(self.tmp)
        self.db = DeployDB(self.paths.db_file)
        self.addCleanup(self.db.close)
        self.ctx = Context(cfg=DeployConfig(organization="clinica-x"), paths=self.paths, db=self.db)
        self.paths.data_dir.mkdir(parents=True, exist_ok=True)

    def binary(self):
        from vyonix_deploy.steps import pacs
        b = pacs.binary(self.ctx)
        b.parent.mkdir(parents=True, exist_ok=True)
        b.write_bytes(b"MZ")
        return b

    def test_engine_config_is_locked_down_and_secret_in_vault(self):
        from vyonix.secrets import SecretStore
        from vyonix_deploy.steps import pacs
        st = pacs.EngineConfigStep()
        before = st.capture(self.ctx)
        from vyonix_deploy.errors import DeployError
        with self.assertRaises(DeployError):                     # sem o binário do motor
            st.apply(self.ctx)
        self.binary()
        self.assertFalse(st.check(self.ctx))
        st.apply(self.ctx)
        self.assertTrue(st.check(self.ctx))
        cfg = json.loads(pacs.config_file(self.ctx).read_text(encoding="utf-8"))
        self.assertEqual(cfg["Plugins"], [])
        self.assertFalse(cfg["RemoteAccessAllowed"])
        self.assertTrue(cfg["AuthenticationEnabled"])
        self.assertFalse(cfg["OverwriteInstances"])
        for k in ("DicomAlwaysAllowFind", "DicomAlwaysAllowGet", "DicomAlwaysAllowMove", "DicomAlwaysAllowFindWorklist"):
            self.assertFalse(cfg[k], k)                                   # Q/R DIMSE fora do Core: desligado
        self.assertEqual(cfg["DicomModalities"], {})
        pw = SecretStore(self.paths.data_dir).get(pacs.SECRET).decode()
        self.assertEqual(cfg["RegisteredUsers"], {pacs.USER: pw})
        self.assertGreaterEqual(len(pw), 24)
        self.assertNotIn(pw, json.dumps(st.describe(self.ctx)))           # o plano/relatório não mostra a senha
        self.assertTrue(pacs.storage_dir(self.ctx).is_dir())
        st.apply(self.ctx)                                                 # idempotente: mesma senha
        self.assertEqual(json.loads(pacs.config_file(self.ctx).read_text(encoding="utf-8"))["RegisteredUsers"],
                         {pacs.USER: pw})
        st.rollback(self.ctx, before)
        self.assertFalse(pacs.config_file(self.ctx).exists())
        self.assertTrue(pacs.storage_dir(self.ctx).is_dir())                # imagens nunca são apagadas

    def test_core_settings_merge_rollback_and_survive_core_repair(self):
        from vyonix_deploy.steps import pacs
        from vyonix_deploy.steps.core import core_config
        f = self.paths.data_dir / "config.json"
        f.write_text(json.dumps(core_config(self.ctx)), encoding="utf-8")
        st = pacs.CoreSettingsStep()
        before = st.capture(self.ctx)
        self.assertFalse(st.check(self.ctx))
        st.apply(self.ctx)
        self.assertTrue(st.check(self.ctx))
        cur = json.loads(f.read_text(encoding="utf-8"))
        self.assertEqual(cur["pacs_orthanc_url"], "http://127.0.0.1:8042")
        self.assertEqual(cur["mode"], "edge")
        self.assertNotIn("password", json.dumps(cur).lower())
        # o reparo do Core regrava config.json a partir de core_config: os ajustes do PACS continuam
        self.assertEqual(core_config(self.ctx)["pacs_orthanc_username"], pacs.USER)
        self.assertEqual(core_config(self.ctx), cur)
        st.rollback(self.ctx, before)
        self.assertNotIn("pacs_orthanc_url", json.loads(f.read_text(encoding="utf-8")))

    def test_activation_plan_order(self):
        from vyonix_deploy.modules import activation_steps
        ids = [s.id for s in activation_steps(self.ctx, "pacs")]
        for a, b in (("module.pacs.entitlement", "pacs.engine.config"), ("pacs.engine.config", "service.VyonixPacsEngine"),
                     ("service.VyonixPacsEngine", "acl.pacs.storage"),
                     ("service.VyonixPacsEngine", "running.VyonixPacsEngine"), ("running.VyonixPacsEngine",
                                                                                  "pacs.core.settings"),
                     ("pacs.core.settings", "module.pacs.test"), ("module.pacs.test", "module.pacs.enable")):
            self.assertLess(ids.index(a), ids.index(b), (a, b))
        self.assertIn("firewall.pacs-dicom", ids)
        # a conta virtual do serviço só existe depois do registro: permissões que a usam vêm depois
        steps = activation_steps(self.ctx, "pacs")
        svc_at = ids.index("service.VyonixPacsEngine")
        for i, st in enumerate(steps):
            grants = [a for a, _r in getattr(st, "grants", [])] + ([st.account] if hasattr(st, "account")
                                                                   and st.id.startswith("grant") else [])
            if any("VyonixPacsEngine" in g for g in grants):
                self.assertGreater(i, svc_at, st.id)
        self.assertNotIn("pacs.engine.config", [s.id for s in activation_steps(self.ctx, "print")])

    def test_engine_service_refuses_plugins(self):
        from vyonix.pacs.engine_host import EngineProcess
        b = self.binary()
        c = self.tmp / "o.json"
        c.write_text(json.dumps({"Plugins": ["C:/x/DicomWeb.dll"]}), encoding="utf-8")
        with self.assertRaises(RuntimeError):
            EngineProcess(b, c).start()


if __name__ == "__main__":
    unittest.main()
