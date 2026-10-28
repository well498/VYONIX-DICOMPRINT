"""Backup automático diário do PACS (VyonixWorker) e seu reflexo no monitoramento.
Plataforma real, PostgreSQL real; motor DUBLÊ DE TESTE ``MemoryBackend``; relógio simulado; dados sintéticos."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta

from tests_platform.pacs_support import make_dicom, uid
from tests_platform.support import require_db
from tests_platform.test_pacs import ApiBase


def setUpModule():
    global db
    db = require_db()
    from tests_platform import test_pacs
    test_pacs.db = db


class Clock:
    def __init__(self, wall: datetime):
        self.wall, self.mono = wall, 1000.0

    def advance(self, **kw):
        d = timedelta(**kw)
        self.wall += d
        self.mono += d.total_seconds()


class BackupTask(ApiBase):
    def setUp(self):
        super().setUp()
        from vyonix.pacs.backup_task import PacsBackupTask
        self.c = self.login()
        self.dest = self.tmp / "backup-pacs"
        self.clock = Clock(datetime(2026, 10, 27, 1, 0))
        self.task = PacsBackupTask(self.plat, now=lambda: self.clock.wall, monotonic=lambda: self.clock.mono)

    def ingest(self, n=2):
        start = getattr(self, "_n", 0)
        self._n = start + n
        body, ctype = self.stow_body(*[make_dicom(study=uid(7), series=uid(7, 1), sop=uid(7, 1, i + 1), fill=i + 1)
                                       for i in range(start, start + n)])
        r = self.c.post("/api/v1/pacs/dicomweb/studies", content=body, headers={"Content-Type": ctype})
        self.assertEqual(r.status_code, 200, r.text)

    def configure(self):
        self.plat.cfg.extra.update({"pacs_backup_dir": str(self.dest), "pacs_backup_hour": 2})

    def test_disabled_without_destination(self):
        self.assertEqual(self.task(), {"skipped": "pasta de backup não configurada"})

    def test_daily_schedule_incremental_and_verified(self):
        self.license_and_enable()
        self.ingest(2)
        self.configure()
        self.assertIn("fora do horário", self.task()["skipped"])          # 01:00, antes das 02:00
        self.clock.advance(hours=1, minutes=5)
        st = self.task()
        self.assertTrue(st["ok"], st)
        self.assertEqual((st["instances"], st["copied"], st["verified"]), (2, 2, True))
        self.assertEqual(json.loads((self.dest / "last_run.json").read_text(encoding="utf-8"))["local_date"],
                         "2026-10-27")
        self.assertIn("já feito hoje", self.task()["skipped"])
        self.ingest(1)
        self.clock.advance(days=1)
        st = self.task()
        self.assertEqual((st["instances"], st["copied"]), (3, 1))          # incremental
        from vyonix.pacs import backup
        self.assertTrue(backup.verify(self.dest)["valid"])

    def test_module_disabled_is_skipped(self):
        self.configure()
        self.clock.advance(hours=3)
        self.assertEqual(self.task(), {"skipped": "módulo PACS não habilitado"})

    def test_engine_failure_recorded_and_retried_after_an_hour(self):
        self.license_and_enable()
        self.ingest(1)
        self.configure()
        self.clock.advance(hours=2)
        self.b.down = True
        st = self.task()
        self.assertFalse(st["ok"])
        self.assertIn("error", st)
        self.assertIn("fora do horário", self.task()["skipped"])         # sem repetir em seguida
        self.b.down = False
        self.clock.advance(minutes=61)
        self.assertTrue(self.task()["ok"])

    def test_monitoring_reports_backup(self):
        url = "/api/v1/health/detail"
        self.license_and_enable()
        self.ingest(1)
        self.configure()
        h = self.c.get(url).json()
        self.assertEqual(h["status"], "atenção")
        self.assertTrue(any("Nenhum backup automático" in p for p in h["problems"]))
        from vyonix.pacs import backup_task
        self.task.now = datetime.now
        self.task.monotonic = lambda: 10 ** 9
        st = self.task()
        if not st.get("ok"):                     # antes das 02:00 no relógio real: força a execução
            self.plat.cfg.extra["pacs_backup_hour"] = 0
            st = self.task()
        self.assertTrue(st["ok"], st)
        h = self.c.get(url).json()
        self.assertEqual(h["status"], "ok", h["problems"])
        self.assertEqual(h["components"]["pacs_backup"]["instances"], 1)
        self.assertNotIn(str(self.dest), json.dumps(h))                   # não expõe o caminho
        old = backup_task.read_status(self.dest)
        old["finished_at"] = (datetime.now() - timedelta(hours=40)).isoformat(timespec="seconds")
        (self.dest / "last_run.json").write_text(json.dumps(old), encoding="utf-8")
        h = self.c.get(url).json()
        self.assertTrue(any("há 40 h" in p for p in h["problems"]), h["problems"])
        old.update(ok=False, error="disco cheio")
        (self.dest / "last_run.json").write_text(json.dumps(old), encoding="utf-8")
        h = self.c.get(url).json()
        self.assertTrue(any("falhou: disco cheio" in p for p in h["problems"]))
        self.assertEqual(h["status"], "atenção")


class WorkerWiring(unittest.TestCase):
    def test_build_worker_includes_backup(self):
        from vyonix.config import Config
        from vyonix.context import build
        from vyonix.events.worker import build_worker
        import tempfile
        from pathlib import Path
        plat = build(Config(data_dir=Path(tempfile.mkdtemp(prefix="vyx-w-"))), db=db)
        names = [getattr(fn, "__name__", "") for _i, fn, _l in build_worker(plat).periodic]
        self.assertEqual(names, ["pacs-sync", "pacs-backup"])


if __name__ == "__main__":
    unittest.main()
