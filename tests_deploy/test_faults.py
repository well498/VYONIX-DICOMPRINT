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


if __name__ == "__main__":
    unittest.main()
