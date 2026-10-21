"""Motor do DEPLOY: plano, aprovação, idempotência, reversão e retomada após interrupção real
(processo encerrado à força). Arquivos e banco SQLite reais numa pasta temporária."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from tests_deploy.helpers import FileStep
from vyonix_deploy.config import DeployConfig, NetworkChoice
from vyonix_deploy.db import DeployDB
from vyonix_deploy.engine import Context, Engine
from vyonix_deploy.errors import DeployError, NotApproved
from vyonix_deploy.paths import default_paths
from vyonix_deploy.steps.files import DirectoryStep

ROOT = Path(__file__).resolve().parents[1]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vyx-deploy-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.paths = default_paths(self.tmp)
        self.db = DeployDB(self.paths.db_file)
        self.addCleanup(self.db.close)
        self.ctx = Context(cfg=DeployConfig(), paths=self.paths, db=self.db)
        self.w = self.tmp / "work"

    def engine(self, steps_fn):
        return Engine(self.ctx, lambda ctx, kind: steps_fn())

    def run_all(self, eng, kind="install", **approve):
        rid = eng.new_run(kind)
        eng.save_plan(rid, eng.plan(kind))
        eng.approve(rid, **approve)
        return rid, eng.execute(rid)


class EngineTest(Base):
    def steps(self, **kw):
        return [DirectoryStep("w", self.w, "de trabalho"), FileStep("a", self.w / "a.txt", "A"),
                FileStep("b", self.w / "b.txt", "B", **kw)]

    def test_apply_then_second_run_changes_nothing(self):
        steps = self.steps()
        rid, st = self.run_all(self.engine(lambda: steps))
        self.assertEqual(st, "succeeded")
        self.assertEqual([s["status"] for s in self.db.steps(rid)], ["done", "done", "done"])
        steps2 = self.steps()
        eng = self.engine(lambda: steps2)
        items = eng.plan("install")
        self.assertTrue(all(i.already for i in items))
        rid2, st2 = self.run_all(eng)
        self.assertEqual(st2, "succeeded")
        self.assertEqual([s["status"] for s in self.db.steps(rid2)], ["already"] * 3)
        self.assertEqual((steps2[1].applied(), steps2[2].applied()), (1, 1))      # contadores da 1ª execução

    def test_failure_rolls_back_previous_steps(self):
        self.w.mkdir()
        (self.w / "a.txt").write_text("valor antigo")
        rid, st = self.run_all(self.engine(lambda: self.steps(fail_verify=True)))
        self.assertEqual(st, "rolled_back")
        self.assertEqual((self.w / "a.txt").read_text(), "valor antigo")          # estado anterior restaurado
        self.assertFalse((self.w / "b.txt").exists())
        statuses = [s["status"] for s in self.db.steps(rid)]
        self.assertEqual(statuses, ["already", "rolled_back", "failed"])
        self.assertIn("revertidas", self.db.run(rid)["message"])

    def test_partial_approval(self):
        rid, st = self.run_all(self.engine(self.steps), items=["dir.w", "file.a"])
        self.assertEqual(st, "succeeded")
        self.assertTrue((self.w / "a.txt").exists())
        self.assertFalse((self.w / "b.txt").exists())
        self.assertEqual(self.db.steps(rid)[2]["status"], "not_approved")

    def test_nothing_changes_before_approval(self):
        eng = self.engine(self.steps)
        rid = eng.new_run("install")
        eng.save_plan(rid, eng.plan("install"))
        with self.assertRaises(DeployError):
            eng.execute(rid)
        self.assertFalse(self.w.exists())

    def test_approval_rules(self):
        class Critical(FileStep):
            confirm = "ALTERAR IP"
        eng = self.engine(lambda: [Critical("c", self.tmp / "c.txt", "x")])
        rid = eng.new_run("install")
        eng.save_plan(rid, eng.plan("install"))
        with self.assertRaises(NotApproved):
            eng.approve(rid)
        with self.assertRaises(NotApproved):
            eng.approve(rid, confirmations={"file.c": "alterar"})
        with self.assertRaises(NotApproved):
            eng.approve(rid, items=["inexistente"])
        with self.assertRaises(NotApproved):
            eng.approve(rid, expected_sha="0" * 64, confirmations={"file.c": "ALTERAR IP"})
        a = eng.approve(rid, confirmations={"file.c": "ALTERAR IP"}, user="DOMINIO\\admin")
        self.assertEqual(a["user"], "DOMINIO\\admin")
        self.assertEqual(json.loads(self.db.run(rid)["approval_json"])["plan_sha"], self.db.run(rid)["plan_sha"])

    def test_resume_after_process_killed(self):
        go, started = self.tmp / "go", self.tmp / "started"
        script = self.tmp / "runner.py"
        script.write_text(textwrap.dedent(f"""
            import sys
            sys.path.insert(0, {str(ROOT)!r})
            from pathlib import Path
            from tests_deploy.helpers import FileStep
            from vyonix_deploy.config import DeployConfig
            from vyonix_deploy.db import DeployDB
            from vyonix_deploy.engine import Context, Engine
            from vyonix_deploy.paths import default_paths
            from vyonix_deploy.steps.files import DirectoryStep
            tmp = Path({str(self.tmp)!r}); w = tmp / "work"
            paths = default_paths(tmp); db = DeployDB(paths.db_file)
            steps = lambda: [DirectoryStep("w", w, "x"), FileStep("a", w / "a.txt", "A"),
                             FileStep("b", w / "b.txt", "B", wait_for=tmp / "go", started=tmp / "started"),
                             FileStep("c", w / "c.txt", "C")]
            eng = Engine(Context(cfg=DeployConfig(), paths=paths, db=db), lambda c, k: steps())
            rid = eng.new_run("install"); eng.save_plan(rid, eng.plan("install")); eng.approve(rid)
            print(rid, flush=True)
            eng.execute(rid)
        """))
        p = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, text=True)
        rid = p.stdout.readline().strip()
        deadline = time.time() + 30
        while not started.exists() and time.time() < deadline:
            time.sleep(0.05)
        self.assertTrue(started.exists(), "passo b não começou")
        p.kill()                                         # queda no meio do passo b
        p.wait(10)
        p.stdout.close()
        rows = {r["step_id"]: r["status"] for r in self.db.steps(rid)}
        self.assertEqual((rows["file.a"], rows["file.b"], rows["file.c"]), ("done", "applying", "pending"))
        self.assertEqual(self.db.run(rid)["status"], "running")
        go.write_text("1")
        steps = [DirectoryStep("w", self.w, "x"), FileStep("a", self.w / "a.txt", "A"),
                 FileStep("b", self.w / "b.txt", "B"), FileStep("c", self.w / "c.txt", "C")]
        self.assertEqual(Engine(self.ctx, lambda c, k: steps).execute(rid), "succeeded")
        self.assertEqual(steps[1].applied(), 1)          # passo a confirmado antes: não reaplicado
        self.assertEqual(steps[2].applied(), 2)          # passo b: reaplicado após a queda
        self.assertEqual([r["status"] for r in self.db.steps(rid)], ["done"] * 4)
        ev = [e["message"] for e in self.db.x("SELECT message FROM events WHERE run_id = ?", (rid,))]
        self.assertTrue(any("retomando" in m.lower() for m in ev))

    def test_plan_mismatch_after_upgrade_refused(self):
        eng = self.engine(self.steps)
        rid = eng.new_run("install")
        eng.save_plan(rid, eng.plan("install"))
        eng.approve(rid)
        other = Engine(self.ctx, lambda c, k: self.steps()[:2])
        with self.assertRaises(DeployError):
            other.execute(rid)


class ConfigTest(unittest.TestCase):
    def test_validation(self):
        DeployConfig().validate()
        for bad in (dict(organization="X Y"), dict(https_port=80), dict(https_port=5544, pg_port=5544),
                    dict(firewall_sources=["10.0.0.0/33"])):
            with self.assertRaises(DeployError):
                DeployConfig(**bad).validate()
        with self.assertRaises(DeployError):
            DeployConfig(network=NetworkChoice(mode="static", interface="Ethernet", ip="10.0.0.5", prefix=24,
                                               gateway="10.0.1.1")).validate()
        DeployConfig(network=NetworkChoice(mode="static", interface="Ethernet", ip="10.0.0.5", prefix=24,
                                           gateway="10.0.0.1", dns=["10.0.0.2"])).validate()
        with self.assertRaises(DeployError):
            DeployConfig.from_dict({"inexistente": 1})


if __name__ == "__main__":
    unittest.main()
