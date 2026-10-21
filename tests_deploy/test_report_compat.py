"""Relatório PDF/manifesto (redação, histórico sem sobrescrita, cadeia, adulteração) e regras de
compatibilidade a partir de inventários."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from tests_deploy.helpers import FileStep
from vyonix_deploy import compat, redact, report
from vyonix_deploy.config import DeployConfig
from vyonix_deploy.db import DeployDB
from vyonix_deploy.engine import Context, Engine, Step
from vyonix_deploy.paths import default_paths

GB = 1024 ** 3
PEM = "-----BEGIN PRIVATE KEY-----\nMIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQg\n-----END PRIVATE KEY-----"


class Leaky(Step):
    """Passo cujo estado observado contém segredos (para provar a redação)."""
    id = "leaky"
    title = "Item com segredos no estado"

    def observe(self, ctx):
        return {"url": "postgresql://vyonix_app:SuperSegredo123@127.0.0.1:5544/vyonix", "key": PEM,
                "password": "SuperSegredo123", "nota": "senha=SuperSegredo123", "blob": "dpapi:" + "A" * 40}

    def check(self, ctx):
        return True


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vyx-rep-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        os.environ["VYONIX_DEPLOY_ROOT"] = str(self.tmp)
        self.addCleanup(os.environ.pop, "VYONIX_DEPLOY_ROOT", None)
        self.paths = default_paths(self.tmp)
        self.db = DeployDB(self.paths.db_file)
        self.addCleanup(self.db.close)

    def _run(self, steps):
        ctx = Context(cfg=DeployConfig(), paths=self.paths, db=self.db, inventory={"os": {"caption": "Teste"}})
        eng = Engine(ctx, lambda c, k: steps)
        rid = eng.new_run("install")
        eng.save_plan(rid, eng.plan("install"))
        eng.approve(rid)
        eng.execute(rid)
        obs = {s.id: s.observe(ctx) for s in steps}
        return rid, report.generate(self.db, self.paths, rid, observed=obs, secrets=["SuperSegredo123"])

    def test_redaction_history_chain_and_tamper(self):
        rid, r1 = self._run([Leaky(), FileStep("a", self.tmp / "a.txt", "A")])
        body = Path(r1["manifest"]).read_text(encoding="utf-8")
        self.assertEqual(redact.forbidden_hits(body, ["SuperSegredo123"]), [])
        self.assertNotIn("SuperSegredo123", body)
        self.assertNotIn("PRIVATE KEY", body)
        m = json.loads(body)
        self.assertEqual(m["schema"], "vyonix-deploy-manifest/1")
        self.assertEqual(m["pdf"]["sha256"], report.sha256_file(Path(r1["pdf"])))
        self.assertIsNone(m["previous_manifest_sha256"])
        try:
            from pypdf import PdfReader
            text = "\n".join(p.extract_text() for p in PdfReader(r1["pdf"]).pages)
            self.assertIn("Relatório técnico de implantação", text)
            self.assertNotIn("SuperSegredo123", text)
            self.assertNotIn("PRIVATE KEY", text)
        except ImportError:
            if os.environ.get("VYONIX_REQUIRE_PYPDF"):
                raise
        time.sleep(1.1)
        rid2, r2 = self._run([FileStep("b", self.tmp / "b.txt", "B")])
        self.assertNotEqual(r1["pdf"], r2["pdf"])                         # nunca sobrescreve
        self.assertTrue(Path(r1["pdf"]).exists())
        m2 = json.loads(Path(r2["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(m2["previous_manifest_sha256"], r1["manifest_sha256"])
        self.assertEqual(report.verify_chain(self.db), [])
        p = Path(r1["manifest"])                                          # alteração feita fora do VYONIX
        p.write_text(p.read_text(encoding="utf-8").replace('"install"', '"repair"'), encoding="utf-8")
        probs = report.verify_chain(self.db)
        self.assertTrue(any("alterado" in x for x in probs))

    def test_redact_helpers(self):
        s = redact.text("conexão postgresql://u:abc123@h/db e password: xyz e " + PEM)
        self.assertNotIn("abc123", s)
        self.assertNotIn("xyz", s)
        self.assertNotIn("BEGIN PRIVATE", s)
        v = redact.value({"admin_password": "Senha-1234", "nested": {"pfx_password": "x", "ok": "valor"}})
        self.assertEqual(v["admin_password"], "***")
        self.assertEqual(v["nested"], {"pfx_password": "***", "ok": "valor"})


def inv(**kw):
    base = {"os": {"caption": "Windows Server 2022", "build": 20348, "arch": "64 bits"}, "admin": True,
            "computer": {"memory": 16 * GB}, "disks": [{"drive": "C:", "free": 200 * GB, "size": 500 * GB}],
            "ports": [], "services": [], "firewall_profiles": [{"name": "Domain", "enabled": True}],
            "previous": {}}
    base.update(kw)
    return base


class CompatTest(unittest.TestCase):
    def levels(self, i, cfg=None):
        return {f.id: f.level for f in compat.evaluate(i, cfg or DeployConfig())}

    def test_ok_server(self):
        lv = self.levels(inv())
        self.assertNotIn("blocker", lv.values())

    def test_blockers(self):
        lv = self.levels(inv(os={"caption": "Windows 10 1607", "build": 14393, "arch": "64 bits"}, admin=False,
                             computer={"memory": 2 * GB}, disks=[{"drive": "C:", "free": 5 * GB}],
                             ports=[{"port": 8444, "process": "nginx", "pid": 10}]))
        for k in ("os", "admin", "memory", "disk", "port-8444"):
            self.assertEqual(lv[k], "blocker", k)

    def test_alerts_and_info(self):
        lv = self.levels(inv(computer={"memory": 6 * GB}, disks=[{"drive": "C:", "free": 30 * GB}],
                             firewall_profiles=[{"name": "Public", "enabled": False}], reboot_pending=True,
                             services=[{"name": "postgresql-x64-14", "state": "Running"}],
                             previous={"dicom_print": {"name": "VyonixDicomPrint"}},
                             ports=[{"port": 5544, "process": "postgres", "pid": 1}]))
        self.assertEqual((lv["memory"], lv["disk"], lv["firewall"], lv["reboot"]), ("alert",) * 4)
        self.assertEqual((lv["other-postgres"], lv["dicom-print"], lv["port-5544"]), ("info",) * 3)


if __name__ == "__main__":
    unittest.main()
