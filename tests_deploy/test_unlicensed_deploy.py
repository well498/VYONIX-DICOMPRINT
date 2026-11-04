"""DEPLOY sem licença da plataforma (decisão de 04/11/2026): a ativação de módulos não tem etapa de licença, não
monta o licenciamento e não lê/grava a pasta de licenciamento compartilhada com o VYONIX DICOM Print."""
from __future__ import annotations

import inspect
import shutil
import tempfile
import unittest
from pathlib import Path

from vyonix_deploy.config import DeployConfig
from vyonix_deploy.db import DeployDB
from vyonix_deploy.engine import Context
from vyonix_deploy.paths import default_paths


class UnlicensedDeploy(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vyx-dep-free-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.paths = default_paths(self.tmp)
        self.db = DeployDB(self.paths.db_file)
        self.addCleanup(self.db.close)
        self.ctx = Context(cfg=DeployConfig(organization="clinica-x"), paths=self.paths, db=self.db)

    def test_activation_has_no_license_step(self):
        from vyonix_deploy import modules
        for code in ("print", "pacs", "ris", "report"):
            ids = [s.id for s in modules.activation_steps(self.ctx, code)]
            self.assertFalse([i for i in ids if "entitlement" in i or "licen" in i], (code, ids))
            self.assertEqual(ids[0], f"module.{code}.dependencies")
        src = inspect.getsource(modules)
        self.assertNotIn("Machine.build", src)
        self.assertNotIn("module_ok", src)

    def test_report_installation_id_does_not_touch_licensing_folder(self):
        from vyonix_deploy import report
        a = report._installation_id(self.paths)
        self.assertTrue(a.startswith("VYXP-"))
        self.assertEqual(report._installation_id(self.paths), a)          # estável
        self.assertFalse(self.paths.licensing.exists())                    # cofre do DICOM Print não tocado


if __name__ == "__main__":
    unittest.main()
