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

    def test_backup_settings_default_custom_and_validation(self):
        from vyonix_deploy.errors import DeployError
        from vyonix_deploy.steps import pacs
        from vyonix_deploy.steps.core import core_config
        f = self.paths.data_dir / "config.json"
        f.write_text(json.dumps(core_config(self.ctx)), encoding="utf-8")
        pacs.CoreSettingsStep().apply(self.ctx)
        cur = json.loads(f.read_text(encoding="utf-8"))
        self.assertEqual(cur["pacs_backup_dir"], str(self.paths.backups / "PACS"))
        self.assertEqual(cur["pacs_backup_hour"], 2)
        self.assertEqual(core_config(self.ctx)["pacs_backup_dir"], cur["pacs_backup_dir"])   # sobrevive ao reparo
        self.ctx.cfg = DeployConfig.from_dict({"organization": "clinica-x", "pacs_backup_dir": "E:/VYONIX-Backup",
                                                "pacs_backup_hour": 23})
        st = pacs.CoreSettingsStep()
        self.assertFalse(st.check(self.ctx))
        st.apply(self.ctx)
        cur = json.loads(f.read_text(encoding="utf-8"))
        self.assertEqual((cur["pacs_backup_dir"], cur["pacs_backup_hour"]), (str(Path("E:/VYONIX-Backup")), 23))
        with self.assertRaises(DeployError):
            DeployConfig(pacs_backup_hour=24).validate()
        steps = {s.id: s for s in pacs.engine_steps(self.ctx)}
        acl = steps["acl.pacs.backup"]
        self.assertEqual(sorted(a for a, _ in acl.grants)[-1], "NT SERVICE\\VyonixWorker")
        self.assertNotIn("Everyone", str(acl.grants))
        ids = list(steps)
        self.assertLess(ids.index("dir.pacs.backup"), ids.index("acl.pacs.backup"))

    def test_diagnose_reports_pacs_backup(self):
        from datetime import datetime, timedelta
        from vyonix_deploy.diagnose import _pacs_backup
        f = self.paths.data_dir / "config.json"
        self.assertEqual(_pacs_backup(self.ctx), [])                          # sem configuração: nada a apontar
        dest = self.tmp / "bkp"
        f.write_text(json.dumps({"pacs_backup_dir": str(dest)}), encoding="utf-8")
        ids = [p.id for p in _pacs_backup(self.ctx)]
        self.assertIn("pacs.backup.none", ids)
        dest.mkdir()
        st = {"ok": True, "finished_at": datetime.now().isoformat(timespec="seconds")}
        (dest / "last_run.json").write_text(json.dumps(st), encoding="utf-8")
        self.assertFalse([p for p in _pacs_backup(self.ctx) if p.id != "pacs.backup.disk"])
        st = {"ok": False, "error": "motor sem resposta",
              "finished_at": (datetime.now() - timedelta(hours=50)).isoformat(timespec="seconds")}
        (dest / "last_run.json").write_text(json.dumps(st), encoding="utf-8")
        probs = {p.id: p for p in _pacs_backup(self.ctx)}
        self.assertIn("motor sem resposta", probs["pacs.backup.failed"].detail)
        self.assertIn("50 h", probs["pacs.backup.stale"].detail)
        self.assertTrue(all(not p.destructive for p in probs.values()))

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

    def test_every_permission_uses_a_known_right(self):
        """Os direitos são traduzidos só no Windows; um código desconhecido reverteu a ativação (run 40085298672)."""
        from vyonix_deploy.modules import activation_steps
        from vyonix_deploy.plans import install_steps
        from vyonix_deploy.steps.files import RIGHTS, AclGrantStep, AclStep
        steps = activation_steps(self.ctx, "pacs") + install_steps(self.ctx)
        checked = 0
        for st in steps:
            if isinstance(st, AclStep):
                for acct, right in st.grants:
                    self.assertIn(right, RIGHTS, f"{st.id}: {acct} → {right}")
                    checked += 1
            elif isinstance(st, AclGrantStep):
                self.assertIn(st.right, RIGHTS, st.id)
                checked += 1
        self.assertGreater(checked, 10)

    def test_update_repair_and_uninstall_know_the_engine(self):
        """Com o PACS ativado, o motor também executa VyonixPlatform.exe da pasta do programa: o instalador precisa
        pará-lo antes de copiar (a atualização falhou com código 5, run 40087337898), o reparo/atualização precisa
        reiniciá-lo e a desinstalação precisa removê-lo."""
        from pathlib import Path as P
        from vyonix_deploy.plans import build, install_steps
        from vyonix_deploy.steps import pacs
        from vyonix_deploy.steps.update import uninstall_steps
        self.assertNotIn("running.VyonixPacsEngine", [s.id for s in install_steps(self.ctx)])   # módulo não ativado
        pacs.config_file(self.ctx).parent.mkdir(parents=True, exist_ok=True)
        pacs.config_file(self.ctx).write_text("{}", encoding="utf-8")
        for kind in ("repair", "install"):
            ids = [s.id for s in build(self.ctx, kind)]
            self.assertIn("running.VyonixPacsEngine", ids, kind)
            self.assertLess(ids.index("running.VyonixCore"), ids.index("running.VyonixPacsEngine"))
            self.assertEqual(len(ids), len(set(ids)), f"passos repetidos em {kind}")
        un = [s.id for s in uninstall_steps(self.ctx)]
        self.assertEqual(un[0], "remove.service.VyonixPacsEngine")
        self.assertIn("remove.firewall.pacs-dicom", un)
        iss = (P(__file__).resolve().parents[1] / "installer" / "VyonixPlatform.iss").read_text(encoding="utf-8")
        self.assertIn("Services[0] := 'VyonixPacsEngine'", iss)          # parado na atualização e na desinstalação
        self.assertIn("NSERV = 4", iss)
        self.assertIn("Neutralize(Services[I]", iss.split("function PrepareToInstall", 1)[1])

    def test_engine_service_refuses_plugins(self):
        from vyonix.pacs.engine_host import EngineProcess
        b = self.binary()
        c = self.tmp / "o.json"
        c.write_text(json.dumps({"Plugins": ["C:/x/DicomWeb.dll"]}), encoding="utf-8")
        with self.assertRaises(RuntimeError):
            EngineProcess(b, c).start()


if __name__ == "__main__":
    unittest.main()
