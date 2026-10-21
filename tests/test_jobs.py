"""Fase 4 — fila persistente, processador, impressora VYONIX PDF e acompanhamento do spooler."""

import re
import time
import unittest
from pathlib import Path

try:
    import numpy  # noqa: F401
    import PIL  # noqa: F401
    import pynetdicom  # noqa: F401
    HAS = True
except ImportError:
    HAS = False

from tests.helpers import TempDirTestCase


class FakeBackend:
    """Backend de teste: registra os envios e devolve o resultado configurado."""
    name = "fake"

    def __init__(self):
        self.accept = True
        self.pages = []
        self.status = "queued"

    def list_printers(self):
        from app.core.contracts import PrinterInfo
        return [PrinterInfo(name="Impressora Falsa", driver="fake", is_default=True, paper_sizes=("A4",),
                            resolutions_dpi=(300,), supports_color=False, status_text="pronta", backend="fake")]

    def submit(self, request):
        from app.core.contracts import SpoolResult
        if not self.accept:
            return SpoolResult(accepted=False, spool_job_id=None, error="impressora offline (teste)")
        self.pages.append([p.pixels.shape for p in request.pages()] * 1)
        return SpoolResult(accepted=True, spool_job_id=7, detail="aceito")

    def job_status(self, printer, job_id):
        from app.core.contracts import SpoolStatus
        return SpoolStatus(self.status, self.status)


def pdf_pages(path):
    data = Path(path).read_bytes()
    boxes = re.findall(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", data)
    return [(float(w), float(h)) for w, h in boxes]


@unittest.skipUnless(HAS, "numpy/Pillow/pynetdicom não instalados")
class JobsTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        from app.bootstrap import bootstrap
        from app.printing.backends.pdf import PDF_PRINTER
        self.ctx = bootstrap(data_dir=self.tmp / "data")
        self.ctx.printers.refresh()
        self.PDF = PDF_PRINTER
        self.ctx.settings.update({"printing.default_printer": PDF_PRINTER, "printing.dpi": 150}, actor="t")
        self.device = self.ctx.devices.create({"name": "CT sala 1", "ae_title": "CT_TESTE", "modality": "CT",
                                               "ip_address": "127.0.0.1"}, actor="t")
        self.ctx.devices.set_authorized(self.device.id, True, actor="t")

    def tearDown(self):
        self.ctx.close()
        super().tearDown()

    # ------------------------------------------------------------ auxiliares
    def receive(self, n=3, series="1.2.826.0.1.3680043.8.498.1.1", sop_uids=None):
        from app.dicom import scu
        from tests.dicom_helpers import free_port, make_ct
        if self.ctx.storage_scp.status().state.value != "running":
            port = free_port()
            self.ctx.settings.update({"dicom.storage.bind_address": "127.0.0.1", "dicom.storage.port": port},
                                     actor="t")
            self.ctx.storage_scp.start()
        port = self.ctx.storage_scp.bound[1]
        files = [make_ct(self.tmp / f"in/{series[-3:]}_{i}.dcm", series_uid=series, value=500 + 100 * i,
                         sop_uid=sop_uids[i] if sop_uids else None) for i in range(n)]
        self.assertEqual(scu.store_files("127.0.0.1", port, "VYONIX", files, calling_ae="CT_TESTE"), [0] * n)
        return files

    def run_queue(self, max_jobs=10):
        w = self.ctx.worker
        w.collector.flush(force=True)
        done = []
        for _ in range(max_jobs):
            job = w._claim()
            if job is None:
                break
            w.process(job)
            done.append(job.id)
        return done

    def use_fake(self):
        fake = FakeBackend()
        self.ctx.printers.backends.insert(0, fake)
        self.ctx.printers.refresh()
        self.ctx.settings.update({"printing.default_printer": "Impressora Falsa"}, actor="t")
        return fake

    # ------------------------------------------------------------ testes
    def test_received_series_prints_to_pdf(self):
        from app.jobs.states import JobState
        self.ctx.settings.update({"printing.layout": "2x2", "printing.orientation": "portrait"}, actor="t")
        self.receive(3)
        ids = self.run_queue()
        self.assertEqual(len(ids), 1)
        job = self.ctx.jobs.get_job(ids[0])
        self.assertEqual(job.state, JobState.COMPLETED, job.state_reason)
        self.assertEqual(job.items, 3)
        self.assertEqual(job.page_count, 1)
        self.assertEqual(job.device_id, self.device.id)
        pages = pdf_pages(job.output_path)
        self.assertEqual(len(pages), 1)
        self.assertAlmostEqual(pages[0][0], 595.3, delta=1.0)   # A4 em pontos: tamanho físico correto
        self.assertAlmostEqual(pages[0][1], 841.9, delta=1.0)
        self.assertEqual(job.origins["layout"], "Padrão do sistema")
        hist = [h["to_state"] for h in self.ctx.jobs.history(job.id)]
        self.assertEqual(hist, ["received", "validating", "processing", "waiting_print", "spooled", "completed"])
        # Sem dados do paciente no banco
        self.assertNotIn("SINTETICO", (job.settings, job.state_reason, job.document_name).__repr__())

    def test_resent_series_is_not_printed_twice(self):
        from pydicom.uid import generate_uid
        uids = [generate_uid() for _ in range(2)]
        self.receive(2, sop_uids=uids)
        self.assertEqual(len(self.run_queue()), 1)
        self.receive(2, sop_uids=uids)
        self.assertEqual(self.run_queue(), [])
        self.assertEqual(self.ctx.db.connection().execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)
        actions = [e.action for e in self.ctx.events.query()]
        self.assertIn("job.duplicate", actions)

    def test_profile_by_modality_and_origins(self):
        from app.printing.profiles import PrintProfile
        p = self.ctx.profiles.save(PrintProfile(id=None, name="CT 2x3", layout="2x3", copies=2), actor="t")
        self.ctx.profiles.bind(p.id, "modality", "CT", actor="t")
        self.receive(1)
        job = self.ctx.jobs.get_job(self.run_queue()[0])
        self.assertEqual(job.settings["layout"], "2x3")
        self.assertEqual(job.copies, 2)
        self.assertIn("CT 2x3", job.origins["layout"])
        self.assertEqual(job.origins["paper"], "Padrão do sistema")

    def test_no_printer_fails_clearly(self):
        from app.jobs.states import JobState
        self.ctx.settings.update({"printing.default_printer": ""}, actor="t")
        self.receive(1)
        job = self.ctx.jobs.get_job(self.run_queue()[0])
        self.assertEqual(job.state, JobState.FAILED)
        self.assertIn("Nenhuma impressora", job.state_reason)
        self.assertIsNone(job.next_attempt_at)          # falha permanente: não fica tentando

    def test_transient_failure_retries_then_stops(self):
        from app.jobs.states import JobState
        fake = self.use_fake()
        fake.accept = False
        self.ctx.settings.update({"jobs.max_attempts": 2, "jobs.retry_delay_seconds": 5}, actor="t")
        self.receive(1)
        jid = self.run_queue()[0]
        job = self.ctx.jobs.get_job(jid)
        self.assertEqual(job.state, JobState.FAILED)
        self.assertIsNotNone(job.next_attempt_at)
        self.assertIn("nova tentativa automática (1/2)", job.state_reason)
        self.ctx.jobs.update_fields(jid, next_attempt_at="2000-01-01T00:00:00.000Z")   # vence o intervalo
        self.run_queue()
        job = self.ctx.jobs.get_job(jid)
        self.assertEqual((job.state, job.attempts, job.next_attempt_at), (JobState.FAILED, 2, None))
        fake.accept = True
        self.ctx.jobs.retry(jid, actor="operador")
        self.run_queue()
        job = self.ctx.jobs.get_job(jid)
        self.assertEqual(job.state, JobState.SPOOLED)       # Windows: enviado ≠ impresso
        self.assertEqual(job.spool_job_id, 7)
        fake.status = "printed"
        self.ctx.worker.poll_spooled()
        self.assertEqual(self.ctx.jobs.get_job(jid).state, JobState.COMPLETED)

    def test_spool_deleted_and_gone(self):
        from app.jobs.states import JobState
        fake = self.use_fake()
        self.receive(1, series="1.2.3.4.5.100")
        self.receive(1, series="1.2.3.4.5.200")
        a, b = self.run_queue()
        fake.status = "gone"
        self.ctx.worker.poll_spooled()
        ja = self.ctx.jobs.get_job(a)
        self.assertEqual(ja.state, JobState.SPOOLED)       # sem confirmação: não marca como concluído
        self.assertIn("não informou confirmação", ja.state_reason)
        self.ctx.jobs.update_fields(b, spool_status=None)
        fake.status = "deleted"
        self.ctx.worker.poll_spooled()
        self.assertEqual(self.ctx.jobs.get_job(b).state, JobState.FAILED)
        self.assertEqual(self.ctx.jobs.get_job(a).state, JobState.SPOOLED)   # já saiu do acompanhamento

    def test_hold_release_cancel_reprint(self):
        from app.core.errors import ValidationError
        from app.jobs.states import JobState
        self.ctx.settings.update({"jobs.hold_new": True}, actor="t")
        self.receive(2)
        self.assertEqual(self.run_queue(), [])              # retido não é processado
        jid = self.ctx.jobs.list()[0].id
        self.assertEqual(self.ctx.jobs.get_job(jid).state, JobState.HELD)
        self.ctx.jobs.release(jid, actor="op")
        self.run_queue()
        self.assertEqual(self.ctx.jobs.get_job(jid).state, JobState.COMPLETED)
        with self.assertRaises(ValidationError):
            self.ctx.jobs.cancel(jid, actor="op")           # concluído é terminal
        new = self.ctx.jobs.reprint(jid, actor="op", copies=3)
        job2 = self.ctx.jobs.get_job(new)
        self.assertEqual((job2.parent_job_id, job2.copies, job2.source_type), (jid, 3, "reprint"))
        self.assertEqual(job2.origins["copies"], "Escolha manual (reimpressão)")
        self.ctx.jobs.cancel(new, actor="op")
        self.assertEqual(self.ctx.jobs.get_job(new).state, JobState.CANCELLED)
        self.assertEqual(self.run_queue(), [])

    def test_recovery_after_crash(self):
        from app.jobs.states import JobState
        self.ctx.settings.update({"jobs.hold_new": True}, actor="t")
        self.receive(1, series="1.2.3.4.5.100")
        self.receive(1, series="1.2.3.4.5.200")
        self.ctx.worker.collector.flush(force=True)
        a, b = sorted(j.id for j in self.ctx.jobs.list())
        conn = self.ctx.db.connection()
        conn.execute("UPDATE jobs SET state='waiting_print', submitted_at='2026-01-01T00:00:00.000Z' WHERE id=?", (a,))
        conn.execute("UPDATE jobs SET state='processing' WHERE id=?", (b,))
        self.ctx.worker.recover()
        self.assertEqual(self.ctx.jobs.get_job(a).state, JobState.HELD)        # talvez já impresso: conferir
        self.assertEqual(self.ctx.jobs.get_job(b).state, JobState.FAILED)
        self.assertIsNotNone(self.ctx.jobs.get_job(b).next_attempt_at)       # retomado automaticamente
        self.assertEqual(self.run_queue(), [b])
        self.assertEqual(self.ctx.jobs.get_job(b).state, JobState.COMPLETED)

    def test_pending_autoprint_survives_restart(self):
        from app.bootstrap import bootstrap
        self.receive(2)
        self.ctx.close()
        self.ctx = bootstrap(data_dir=self.tmp / "data")
        self.ctx.printers.refresh()
        self.assertEqual(len(self.run_queue()), 1)

    def test_missing_image_is_permanent_failure(self):
        from app.jobs.states import JobState
        files = self.receive(1)
        self.ctx.worker.collector.flush(force=True)
        row = self.ctx.db.connection().execute("SELECT file_path FROM instances").fetchone()
        Path(row["file_path"]).unlink()
        self.assertTrue(files)
        jid = self.run_queue()[0]
        job = self.ctx.jobs.get_job(jid)
        self.assertEqual(job.state, JobState.FAILED)
        self.assertIsNone(job.next_attempt_at)

    def test_test_page_pdf(self):
        from app.jobs.states import JobState
        jid = self.ctx.jobs.test_page(printer=self.PDF, actor="op",
                                      overrides={"paper": "A3", "orientation": "landscape"})
        self.run_queue()
        job = self.ctx.jobs.get_job(jid)
        self.assertEqual(job.state, JobState.COMPLETED, job.state_reason)
        (w, h), = pdf_pages(job.output_path)
        self.assertAlmostEqual(w, 1190.6, delta=1.5)
        self.assertAlmostEqual(h, 841.9, delta=1.5)

    def test_worker_thread_end_to_end(self):
        from app.jobs.states import JobState
        self.ctx.settings.update({"jobs.collect_seconds": 2}, actor="t")
        self.ctx.runtime.start()
        self.receive(2)
        end = time.monotonic() + 20
        while time.monotonic() < end:
            jobs = self.ctx.jobs.list()
            if jobs and jobs[0].state == JobState.COMPLETED:
                break
            time.sleep(0.2)
        self.assertEqual(jobs[0].state, JobState.COMPLETED)
        statuses = {s.name: s for s in self.ctx.runtime.service_statuses()}
        self.assertEqual(statuses["Fila de impressão"].state.value, "running")
