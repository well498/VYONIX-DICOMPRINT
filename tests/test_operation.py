"""Pausa operacional segura, reinício seguro dos servidores e retenção separada da auditoria (Prompt Mestre §19)."""

import threading
import time
import unittest

try:
    import numpy  # noqa: F401
    import PIL  # noqa: F401
    import pynetdicom  # noqa: F401
    HAS = True
except ImportError:
    HAS = False

from tests.helpers import TempDirTestCase
from tests.test_jobs import FakeBackend


@unittest.skipUnless(HAS, "numpy/Pillow/pynetdicom não instalados")
class OperationPauseTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        from app.bootstrap import bootstrap
        self.ctx = bootstrap(data_dir=self.tmp / "data")
        self.ctx.printers.refresh()
        self.fake = FakeBackend()
        self.ctx.printers.backends.insert(0, self.fake)
        self.ctx.printers.refresh()
        self.ctx.settings.update({"printing.default_printer": "Impressora Falsa", "printing.dpi": 150}, actor="t")
        d = self.ctx.devices.create({"name": "CT sala 1", "ae_title": "CT_TESTE", "modality": "CT",
                                     "ip_address": "127.0.0.1"}, actor="t")
        self.ctx.devices.set_authorized(d.id, True, actor="t")

    def tearDown(self):
        self.ctx.close()
        super().tearDown()

    def receive(self, n=2, series="1.2.826.0.1.3680043.8.498.7.1"):
        from app.dicom import scu
        from tests.dicom_helpers import free_port, make_ct
        if self.ctx.storage_scp.status().state.value != "running":
            self.ctx.settings.update({"dicom.storage.bind_address": "127.0.0.1", "dicom.storage.port": free_port()},
                                     actor="t")
            self.ctx.storage_scp.start()
        port = self.ctx.storage_scp.bound[1]
        files = [make_ct(self.tmp / f"in/{series[-3:]}_{i}.dcm", series_uid=series, value=400 + 50 * i)
                 for i in range(n)]
        self.assertEqual(scu.store_files("127.0.0.1", port, "VYONIX", files, calling_ae="CT_TESTE"), [0] * n)

    def test_state_validation_and_audit(self):
        from app.core.errors import ValidationError
        op = self.ctx.operation
        self.assertFalse(op.state().paused)
        with self.assertRaises(ValidationError):
            op.pause(actor="ui:ana", reason="   ")
        with self.assertRaises(ValidationError):
            op.pause(actor="", reason="troca de papel")
        with self.assertRaises(ValidationError):
            op.pause(actor="ui:ana", reason="x" * 201)
        st = op.pause(actor="ui:ana", reason="Troca do  rolo de papel")
        self.assertTrue(st.paused)
        self.assertEqual((st.actor, st.reason), ("ui:ana", "Troca do rolo de papel"))
        self.assertIsNotNone(st.since)
        self.assertEqual(op.pause(actor="ui:bia", reason="outra").actor, "ui:ana")   # já pausado: idempotente
        st = op.resume(actor="ui:bia")
        self.assertFalse(st.paused)
        self.assertIsNone(st.reason)
        self.assertFalse(op.resume(actor="ui:bia").paused)
        ev = [e for e in self.ctx.events.query() if e.action.startswith("operation.")]
        self.assertEqual([e.action for e in ev], ["operation.resume", "operation.pause"])
        self.assertEqual({e.category for e in ev}, {"admin"})
        self.assertEqual(ev[0].details["paused_by"], "ui:ana")

    def test_pause_keeps_reception_and_holds_queue(self):
        """Pausado: a imagem chega, o trabalho é criado e espera; ao retomar, imprime uma vez."""
        from app.jobs.states import JobState
        op, w = self.ctx.operation, self.ctx.worker
        op.pause(actor="t", reason="manutenção da impressora")
        self.receive(2)
        w.collector.flush(force=True)
        self.assertIsNone(w._next_job())
        job_id = self.ctx.db.connection().execute("SELECT id FROM jobs").fetchone()[0]
        self.assertEqual(self.ctx.jobs.get_job(job_id).state, JobState.RECEIVED)
        self.assertEqual(self.fake.pages, [])
        snap = self.ctx.dashboard.snapshot()
        self.assertTrue(snap.paused)
        self.assertIn("PAUSADO", snap.alerts[0].text)
        op.resume(actor="t")
        job = w._next_job()
        self.assertEqual(job.id, job_id)
        w.process(job)
        self.assertEqual(self.ctx.jobs.get_job(job_id).state, JobState.SPOOLED)
        self.assertEqual(len(self.fake.pages), 1)
        self.assertIsNone(w._next_job())

    def test_pause_lets_running_job_finish(self):
        """A pausa no meio de um trabalho não o interrompe: ele termina e o próximo espera."""
        from app.jobs.states import JobState
        w = self.ctx.worker
        self.receive(1, series="1.2.826.0.1.3680043.8.498.7.2")
        self.receive(1, series="1.2.826.0.1.3680043.8.498.7.3")
        w.collector.flush(force=True)
        first = w._next_job()
        self.ctx.operation.pause(actor="t", reason="pausa durante a impressão")
        w.process(first)
        self.assertEqual(self.ctx.jobs.get_job(first.id).state, JobState.SPOOLED)
        self.assertIsNone(w._next_job())
        self.assertEqual(self.ctx.db.connection().execute(
            "SELECT COUNT(*) FROM jobs WHERE state = 'received'").fetchone()[0], 1)

    def test_pause_shared_between_processes(self):
        """Interface e serviço são processos distintos: o estado vale para outra conexão ao banco."""
        from app.services.operation import OperationControl
        from app.database.connection import Database
        from app.database.repositories.events_repo import EventRepository
        other = Database(self.ctx.db.path)
        try:
            remote = OperationControl(other, EventRepository(other))
            self.ctx.operation.pause(actor="ui:x", reason="teste entre processos")
            self.assertTrue(remote.state().paused)
            remote.resume(actor="servico")
            time.sleep(1.1)                                   # cache de 1 s do laço do processador
            self.assertFalse(self.ctx.operation.is_paused())
        finally:
            other.close()

    def test_worker_thread_obeys_pause(self):
        self.ctx.operation.pause(actor="t", reason="teste do processador")
        self.receive(1, series="1.2.826.0.1.3680043.8.498.7.4")
        self.ctx.worker.start()
        try:
            time.sleep(2.5)
            self.assertEqual(self.fake.pages, [])
            status = {s.name: s for s in self.ctx.runtime.service_statuses()}
            self.assertIn("PAUSADA", status["Fila de impressão"].detail)
            self.ctx.operation.resume(actor="t")
            end = time.monotonic() + 30
            while not self.fake.pages and time.monotonic() < end:
                time.sleep(0.2)
            self.assertEqual(len(self.fake.pages), 1)
        finally:
            self.ctx.worker.stop()


class _FakeSCP:
    def __init__(self, busy_for: float):
        self.until = time.monotonic() + busy_for
        self.restarted_at = None

    def active_associations(self):
        return [{"id": 1}] if time.monotonic() < self.until else []

    def restart(self):
        self.restarted_at = time.monotonic()


class SafeRestartTest(unittest.TestCase):
    def runtime(self):
        from app.services.runtime import CoreRuntime
        return CoreRuntime(storage_scp=None, retention=None, settings_get=lambda k: None)

    def test_waits_for_active_association(self):
        scp = _FakeSCP(busy_for=0.6)
        t0 = time.monotonic()
        self.assertTrue(self.runtime().restart_when_idle(scp, wait_s=5, poll_s=0.05))
        self.assertGreaterEqual(scp.restarted_at - t0, 0.55)

    def test_idle_restarts_immediately(self):
        scp = _FakeSCP(busy_for=0)
        t0 = time.monotonic()
        self.assertTrue(self.runtime().restart_when_idle(scp, wait_s=5, poll_s=0.05))
        self.assertLess(scp.restarted_at - t0, 0.3)

    def test_deadline_still_restarts(self):
        scp = _FakeSCP(busy_for=60)
        self.assertFalse(self.runtime().restart_when_idle(scp, wait_s=0.3, poll_s=0.05))
        self.assertIsNotNone(scp.restarted_at)


class AuditRetentionTest(TempDirTestCase):
    def test_audit_trail_outlives_operational_events(self):
        from app.database.connection import Database
        from app.database.migrations import MIGRATIONS
        from app.database.migrator import migrate
        from app.database.repositories.events_repo import Category, EventRepository
        db = Database(self.tmp / "e.db")
        try:
            migrate(db, MIGRATIONS)
            ev = EventRepository(db)
            for cat in (Category.JOB, Category.DICOM, Category.ADMIN, Category.SECURITY, Category.LICENSE):
                ev.add(level="INFO", category=cat, action=f"{cat}.x", message="antigo")
            ev.add(level="INFO", category=Category.ADMIN, action="admin.velho", message="muito antigo")
            conn = db.connection()
            conn.execute("UPDATE events SET ts = '2025-01-01T00:00:00.000Z' WHERE message = 'antigo'")
            conn.execute("UPDATE events SET ts = '2015-01-01T00:00:00.000Z' WHERE message = 'muito antigo'")
            ev.add(level="INFO", category=Category.JOB, action="job.novo", message="recente")
            removed = ev.purge_older_than(30, audit_days=1825)
            self.assertEqual(removed, 3)          # 2 operacionais antigos + auditoria além de 5 anos
            left = sorted(e.action for e in ev.query())
            self.assertEqual(left, ["admin.x", "job.novo", "license.x", "security.x"])
            # prazo de auditoria nunca menor que o operacional
            self.assertEqual(ev.purge_older_than(3650, audit_days=30), 0)
        finally:
            db.close()

    def test_setting_bounds(self):
        from app.services.settings_service import SettingsService
        d = SettingsService.definition("retention.audit_days")
        self.assertEqual((d.default, d.minimum, d.maximum), (1825, 365, 7300))


if __name__ == "__main__":
    unittest.main()
