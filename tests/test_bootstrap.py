"""F1-01 / F1-09 (parte sem Qt) — inicialização completa, --check e Dashboard."""

import contextlib
import io
import json
import logging

from app.bootstrap import bootstrap
from app.core.contracts import ServiceState
from app.core.errors import DatabaseIntegrityError
from app.database.repositories.events_repo import Category, EventFilter
from app.main import EXIT_OK, EXIT_STARTUP_ERROR, main
from tests.helpers import TempDirTestCase


class BootstrapTest(TempDirTestCase):
    def test_first_and_second_start(self):
        ctx = bootstrap(data_dir=self.tmp, role="ui")
        self.assertEqual(ctx.applied_migrations, [1])
        for d in ctx.paths.all_dirs():
            self.assertTrue(d.is_dir(), d)
        iid = ctx.settings.get("system.installation_id")
        actions = [e.action for e in ctx.events.query(EventFilter(categories=(Category.SYSTEM,)))]
        self.assertIn("app.start", actions)
        self.assertIn("db.migrate", actions)
        ctx.close()
        ctx.close()  # idempotente

        ctx = bootstrap(data_dir=self.tmp, role="ui")
        self.assertEqual(ctx.applied_migrations, [])
        self.assertEqual(ctx.settings.get("system.installation_id"), iid)
        stops = ctx.events.query(EventFilter(text="Encerramento"))
        self.assertEqual(len(stops), 1)
        ctx.close()

    def test_log_level_setting_applies_live(self):
        ctx = bootstrap(data_dir=self.tmp)
        ctx.settings.update({"logging.level": "ERROR"}, actor="t")
        self.assertEqual(logging.getLogger("vyonix").level, logging.ERROR)
        ctx.close()
        ctx = bootstrap(data_dir=self.tmp)
        self.assertEqual(logging.getLogger("vyonix").level, logging.ERROR)
        ctx.close()

    def test_dashboard_snapshot_is_real_and_explicit(self):
        ctx = bootstrap(data_dir=self.tmp)
        s = ctx.dashboard.snapshot()
        self.assertEqual(s.storage_ae, "VYONIX")
        self.assertEqual((s.devices_total, s.jobs_in_queue, s.jobs_failed_24h), (0, 0, 0))
        states = {x.name: x.state for x in s.services}
        self.assertEqual(states["DICOM Storage SCP"], ServiceState.STOPPED)  # --check não inicia serviços
        self.assertEqual(states["DICOM Print SCP"], ServiceState.NOT_IMPLEMENTED)
        self.assertTrue(any("senha de administrador" in a.text for a in s.alerts))
        self.assertTrue(any("uso clínico" in a.text for a in s.alerts))
        ctx.events.add(level="ERROR", category=Category.SPOOLER, action="x", message="falha teste")
        s = ctx.dashboard.snapshot()
        self.assertEqual(len(s.recent_failures), 1)
        ctx.close()

    def test_corrupted_database_stops_startup(self):
        db_file = self.tmp / "machine" / "database" / "vyonix.db"
        db_file.parent.mkdir(parents=True)
        db_file.write_bytes(b"lixo" * 1000)
        with self.assertRaises(DatabaseIntegrityError):
            bootstrap(data_dir=self.tmp)
        self.assertEqual(db_file.read_bytes()[:4], b"lixo")  # nada é sobrescrito automaticamente

    def test_cli_check(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--check", "--data-dir", str(self.tmp)])
        self.assertEqual(code, EXIT_OK)
        summary = json.loads(out.getvalue())
        self.assertEqual(summary["schema_version"], 1)

    def test_cli_check_report_without_console(self):
        import sys
        report = self.tmp / "r" / "check.json"
        saved = sys.stdout
        sys.stdout = None  # executável empacotado sem console
        try:
            code = main(["--check", "--data-dir", str(self.tmp / "d"), "--report", str(report)])
            self.assertEqual(main(["--version"]), EXIT_OK)
        finally:
            sys.stdout = saved
        self.assertEqual(code, EXIT_OK)
        data = json.loads(report.read_text(encoding="utf-8"))
        self.assertTrue(data["ok"])
        self.assertEqual(data["schema_version"], 1)

    def test_cli_bad_argument_returns_code(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--nao-existe"]), 2)

    def test_cli_check_reports_startup_error(self):
        db_file = self.tmp / "machine" / "database" / "vyonix.db"
        db_file.parent.mkdir(parents=True)
        db_file.write_bytes(b"lixo" * 1000)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--check", "--data-dir", str(self.tmp)]), EXIT_STARTUP_ERROR)
