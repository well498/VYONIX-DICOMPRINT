"""Falhas simuladas (somente por variável de ambiente) e reversão segura do banco na atualização."""

import os
import unittest
from unittest import mock

from vyonix_deploy import faults
from vyonix_deploy.steps import core
from vyonix_deploy.steps.services import ServiceRunningStep


class Faults(unittest.TestCase):
    def test_off_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(faults.active("migracao"))
            self.assertFalse(ServiceRunningStep("VyonixCore", "Core")._simulated_failure())

    def test_on_only_when_named(self):
        with mock.patch.dict(os.environ, {faults.VAR: "inicializacao"}):
            self.assertTrue(faults.active("inicializacao"))
            self.assertFalse(faults.active("migracao"))
            self.assertTrue(ServiceRunningStep("VyonixCore", "Core")._simulated_failure())
            self.assertFalse(ServiceRunningStep("VyonixWorker", "Worker")._simulated_failure())
            ok, msg = ServiceRunningStep("VyonixCore", "Core").verify(None)
            self.assertFalse(ok)
            self.assertIn("simulada", msg)

    def test_migration_fault_raises_before_touching_database(self):
        st = core.CoreDatabaseStep()
        with mock.patch.dict(os.environ, {faults.VAR: "migracao"}), \
                mock.patch("vyonix_deploy.steps.core._core_store") as store:
            self.assertFalse(st.check(None))
            with self.assertRaises(Exception) as cm:
                st.apply(None)
            self.assertIn("simulada", str(cm.exception))
            store.assert_not_called()


class RollbackNeverDropsExistingDatabase(unittest.TestCase):
    def _rollback(self, before):
        with mock.patch("vyonix.db.provision.drop") as drop, mock.patch.object(core.pg, "admin_url", return_value="x"):
            ctx = mock.MagicMock()
            core.CoreDatabaseStep().rollback(ctx, before)
            return drop.called

    def test_unknown_state_is_never_dropped(self):
        self.assertFalse(self._rollback({"database": None, "config_file": True}))
        self.assertFalse(self._rollback({}))                 # captura antiga/incompleta
        self.assertFalse(self._rollback({"database": True, "config_file": True}))

    def test_only_database_confirmed_absent_before_is_dropped(self):
        self.assertTrue(self._rollback({"database": False, "config_file": True}))

    def test_capture_marks_unreachable_database_as_unknown(self):
        st = core.CoreDatabaseStep()
        with mock.patch.object(core.CoreDatabaseStep, "observe", return_value={"config_file": True, "postgres": "off"}):
            self.assertIsNone(st.capture(None)["database"])


class ClusterRollback(unittest.TestCase):
    def test_existing_or_unknown_cluster_is_never_removed(self):
        import tempfile
        from pathlib import Path
        from vyonix_deploy.steps import postgres as pg
        with tempfile.TemporaryDirectory() as d:
            data = Path(d) / "data"
            data.mkdir()
            (data / "PG_VERSION").write_text("17")
            st = pg.PgClusterStep(Path(d) / "bin", data)
            for before in ({}, {"initialized": None}, {"initialized": True}):
                st.rollback(mock.MagicMock(), before)
                self.assertTrue((data / "PG_VERSION").exists(), before)
            st.rollback(mock.MagicMock(), {"initialized": False})       # criado nesta execução: pode desfazer
            self.assertFalse(data.exists())


class PostgresOrphans(unittest.TestCase):
    """CI 40951093428 (2.10): o syslogger sobrevivia ao banco encerrado à força e impedia o serviço de subir."""

    def test_no_log_collector_and_old_config_is_updated(self):
        from pathlib import Path
        import tempfile
        from vyonix_deploy.steps import postgres as pg
        ctx = mock.MagicMock()
        ctx.cfg.pg_port = 5544
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            st = pg.PgClusterStep(Path(d) / "bin", data)
            conf = st._conf(ctx)
            self.assertIn("logging_collector = off", conf)
            self.assertNotIn("logging_collector = on", conf)
            (data / "PG_VERSION").write_text("17")
            (data / "pg_hba.conf").write_text(pg.HBA, encoding="utf-8")
            (data / "postgresql.auto.conf").write_text("# x\n" + conf.replace("logging_collector = off",
                                                                                 "logging_collector = on"))
            self.assertFalse(st.check(ctx))                 # instalação existente recebe a configuração nova
            (data / "postgresql.auto.conf").write_text("# x\n" + conf)
            self.assertTrue(st.check(ctx))

    def test_orphans_killed_only_when_database_service_is_stopped(self):
        from vyonix_deploy.steps import postgres as pg
        from vyonix_deploy.steps import services as sv
        ctx = mock.MagicMock()
        states = iter([{"state": "Stopped"}, {"state": "Running"}])
        with mock.patch.object(sv, "query_service", side_effect=lambda n: next(states)), \
                mock.patch.object(sv, "run", return_value=mock.MagicMock(ok=True, out="")), \
                mock.patch.object(sv, "_wait", return_value="Running"), \
                mock.patch.object(pg, "orphan_processes", return_value=[{"pid": 6456}]) as orph, \
                mock.patch.object(sv.time, "sleep"):
            sv.ServiceRunningStep("VyonixPostgreSQL", "PG").apply(ctx)
            orph.assert_called_once_with(ctx.paths.pg_bin, kill=True)
        with mock.patch.object(sv, "query_service", return_value={"state": "Stopped"}), \
                mock.patch.object(sv, "run", return_value=mock.MagicMock(ok=True, out="")), \
                mock.patch.object(sv, "_wait", return_value="Running"), \
                mock.patch.object(pg, "orphan_processes") as orph:
            sv.ServiceRunningStep("VyonixCore", "Core").apply(ctx)     # outros serviços: nunca
            orph.assert_not_called()


if __name__ == "__main__":
    unittest.main()
