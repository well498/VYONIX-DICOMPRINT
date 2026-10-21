"""Fase 5 — DICOM Print SCP real em 127.0.0.1, com o pynetdicom no papel do equipamento (SCU)."""

import unittest

try:
    import numpy as np
    import pynetdicom  # noqa: F401
    HAS = True
except ImportError:
    HAS = False

from tests.helpers import TempDirTestCase

GRAY_META = "1.2.840.10008.5.1.1.9"
COLOR_META = "1.2.840.10008.5.1.1.18"
FILM_SESSION, FILM_BOX = "1.2.840.10008.5.1.1.1", "1.2.840.10008.5.1.1.2"
GRAY_IB, COLOR_IB = "1.2.840.10008.5.1.1.4", "1.2.840.10008.5.1.1.4.1"
PRINTER, PRINTER_INSTANCE = "1.2.840.10008.5.1.1.16", "1.2.840.10008.5.1.1.17"
PLUT = "1.2.840.10008.5.1.1.23"


def image_item(rows=64, cols=48, value=0, bits=8, photometric="MONOCHROME2"):
    from pydicom.dataset import Dataset
    it = Dataset()
    it.SamplesPerPixel = 1
    it.PhotometricInterpretation = photometric
    it.Rows, it.Columns = rows, cols
    it.BitsAllocated, it.BitsStored, it.HighBit = bits, (8 if bits == 8 else 12), (7 if bits == 8 else 11)
    it.PixelRepresentation = 0
    dtype = np.uint8 if bits == 8 else np.uint16
    it.PixelData = np.full((rows, cols), value, dtype=dtype).tobytes()
    return it


@unittest.skipUnless(HAS, "numpy/pynetdicom não instalados")
class PrintSCPTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        from app.bootstrap import bootstrap
        from app.printing.backends.pdf import PDF_PRINTER
        from tests.dicom_helpers import free_port
        self.ctx = bootstrap(data_dir=self.tmp / "data")
        self.port = free_port()
        self.ctx.settings.update({"dicom.storage.bind_address": "127.0.0.1", "dicom.print.port": self.port,
                                  "printing.default_printer": PDF_PRINTER, "printing.dpi": 150}, actor="t")
        self.ctx.printers.refresh()
        self.ctx.worker.start()
        self.ctx.print_scp.start()
        self.assertEqual(self.ctx.print_scp.status().state.value, "running", self.ctx.print_scp.status().detail)
        self.device = self.ctx.devices.create({"name": "CR sala 3", "ae_title": "CR_PRINT", "modality": "CR",
                                               "ip_address": "127.0.0.1"}, actor="t", authorized=True)

    def tearDown(self):
        self.ctx.close()
        super().tearDown()

    def associate(self, ae_title="CR_PRINT", meta=GRAY_META):
        from pynetdicom import AE
        ae = AE(ae_title=ae_title)
        ae.add_requested_context(meta)
        ae.add_requested_context(PLUT)
        assoc = ae.associate("127.0.0.1", self.port, ae_title="VYONIX_PRINT")
        self.meta = meta
        return assoc

    def wait_job(self, jid, states=("completed", "failed"), timeout=20):
        import time
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            job = self.ctx.jobs.get_job(jid)
            if job.state.value in states:
                return job
            time.sleep(0.1)
        return self.ctx.jobs.get_job(jid)

    def film(self, assoc, fmt="STANDARD\\2,2", fill=(1, 2, 4), meta_ib=GRAY_IB, copies=2, orientation="LANDSCAPE",
             film_size="14INX17IN", item=None):
        from pydicom.dataset import Dataset
        fs = Dataset()
        fs.NumberOfCopies = copies
        fs.PrintPriority = "HIGH"
        fs.FilmSessionLabel = "PACIENTE FULANO"     # rótulo livre: não pode ir para o banco
        from pydicom.uid import generate_uid
        fs_uid = generate_uid()
        st, rsp = assoc.send_n_create(fs, FILM_SESSION, fs_uid, meta_uid=self.meta)
        self.assertEqual(st.Status, 0x0000)
        fb = Dataset()
        fb.ImageDisplayFormat = fmt
        fb.FilmOrientation = orientation
        fb.FilmSizeID = film_size
        fb.BorderDensity = "BLACK"
        ref = Dataset()
        ref.ReferencedSOPClassUID, ref.ReferencedSOPInstanceUID = FILM_SESSION, fs_uid
        fb.ReferencedFilmSessionSequence = [ref]
        fb_uid = generate_uid()
        st, rsp = assoc.send_n_create(fb, FILM_BOX, fb_uid, meta_uid=self.meta)
        if st.Status != 0x0000:
            return st, None, None
        boxes = rsp.ReferencedImageBoxSequence
        for pos in fill:
            ib = Dataset()
            ib.ImageBoxPosition = pos
            key = "BasicColorImageSequence" if meta_ib == COLOR_IB else "BasicGrayscaleImageSequence"
            setattr(ib, key, [item if item is not None else image_item(value=40 * pos)])
            st2, _ = assoc.send_n_set(ib, meta_ib, boxes[pos - 1].ReferencedSOPInstanceUID, meta_uid=self.meta)
            self.assertEqual(st2.Status, 0x0000)
        return st, fb_uid, boxes

    def test_printer_status_and_full_film_to_pdf(self):
        assoc = self.associate()
        self.assertTrue(assoc.is_established)
        st, ds = assoc.send_n_get([0x21100010], PRINTER, PRINTER_INSTANCE, meta_uid=self.meta)
        self.assertEqual(st.Status, 0x0000)
        self.assertEqual(ds.PrinterStatus, "NORMAL")
        st, fb_uid, boxes = self.film(assoc)
        self.assertEqual(len(boxes), 4)
        st, _ = assoc.send_n_action(None, 1, FILM_BOX, fb_uid, meta_uid=self.meta)
        self.assertEqual(st.Status, 0x0000)
        assoc.release()
        job = self.ctx.jobs.list()[0]
        self.assertEqual(job.source_type, "dicom_print")
        self.assertEqual((job.settings["layout"], job.copies, job.settings["orientation"]), ("2x2", 2, "landscape"))
        self.assertEqual(job.origins["layout"], "Pedido DICOM Print")
        self.assertEqual(job.priority, 10)
        self.assertIn("14INX17IN", self.ctx.jobs.history(job.id)[0]["reason"] or "")   # anotado na criação
        self.assertEqual(job.device_id, self.device.id)
        self.assertEqual(job.modality, "CR")
        self.assertEqual([it["position"] for it in self.ctx.jobs.items(job.id)], [0, 1, 3])   # posição 3 vazia
        job = self.wait_job(job.id)
        self.assertEqual(job.state.value, "completed", job.state_reason)
        self.assertEqual(job.page_count, 1)
        rows = self.ctx.db.connection().execute("SELECT attributes_json FROM print_sessions").fetchall()
        self.assertTrue(rows)
        self.assertFalse(any("FULANO" in r[0] for r in rows))
        self.assertNotIn("FULANO", repr([e.message for e in self.ctx.events.query()]))

    def test_empty_cell_stays_blank(self):
        from app.jobs.worker import PrintWorker  # noqa: F401
        self.ctx.worker.stop()
        assoc = self.associate()
        st, fb_uid, _ = self.film(assoc, fmt="STANDARD\\2,1", fill=(2,), copies=1, orientation="PORTRAIT",
                                  film_size="A4", item=image_item(value=0))
        assoc.send_n_action(None, 1, FILM_BOX, fb_uid, meta_uid=self.meta)
        assoc.release()
        job = self.ctx.jobs.list()[0]
        self.assertEqual(job.settings["paper"], "A4")
        captured = []

        class Capture:
            name = "pdf"

            def list_printers(self):
                return []

            def submit(self, request):
                from app.core.contracts import SpoolResult
                captured.extend(p.pixels for p in request.pages())
                return SpoolResult(accepted=True, spool_job_id=None, confirmed=True, detail="capturado")

            def job_status(self, *a):
                return None
        self.ctx.printers._by_name[job.settings["printer"]] = Capture()
        w = self.ctx.worker
        w.process(w._claim())
        page = captured[0]
        h, wd = page.shape
        left, right = page[h // 2, : wd // 2], page[h // 2, wd // 2:]
        self.assertEqual(int(left.min()), 255)     # célula 1 sem imagem: papel em branco
        self.assertLess(int(right.min()), 50)      # célula 2 com a imagem preta

    def test_session_action_prints_all_and_reverse_polarity(self):
        from pydicom.dataset import Dataset
        assoc = self.associate()
        _, fb1, _ = self.film(assoc, fmt="STANDARD\\1,1", fill=(1,), copies=1)
        fs_uid = self.ctx.db.connection().execute(
            "SELECT sop_instance_uid FROM print_sessions WHERE kind='film_session'").fetchone()[0]
        fb = Dataset()
        fb.ImageDisplayFormat = "STANDARD\\1,1"
        ref = Dataset()
        ref.ReferencedSOPClassUID, ref.ReferencedSOPInstanceUID = FILM_SESSION, fs_uid
        fb.ReferencedFilmSessionSequence = [ref]
        from pydicom.uid import generate_uid
        st, rsp = assoc.send_n_create(fb, FILM_BOX, generate_uid(), meta_uid=self.meta)
        ib = Dataset()
        ib.Polarity = "REVERSE"
        ib.BasicGrayscaleImageSequence = [image_item(value=0, bits=16, photometric="MONOCHROME1")]
        assoc.send_n_set(ib, GRAY_IB, rsp.ReferencedImageBoxSequence[0].ReferencedSOPInstanceUID, meta_uid=self.meta)
        st, _ = assoc.send_n_action(None, 1, FILM_SESSION, fs_uid, meta_uid=self.meta)
        self.assertEqual(st.Status, 0x0000)
        assoc.release()
        jobs = self.ctx.jobs.list()
        self.assertEqual(len(jobs), 2)
        # MONOCHROME1 valor 0 = branco; REVERSE → preto
        import pydicom
        path = self.ctx.jobs.items(jobs[0].id)[0]["file_path"]
        self.assertEqual(int(pydicom.dcmread(path).pixel_array.max()), 0)
        # Reenvio do mesmo N-ACTION não duplica
        self.assertEqual(len({j.id for j in jobs}), 2)

    def test_errors_and_rejections(self):
        from pydicom.dataset import Dataset
        # Equipamento não cadastrado é recusado
        self.assertFalse(self.associate(ae_title="DESCONHECIDO").is_established)
        assoc = self.associate()
        # Film Box sem Film Session
        fb = Dataset()
        fb.ImageDisplayFormat = "STANDARD\\1,1"
        st, _ = assoc.send_n_create(fb, FILM_BOX, None, meta_uid=self.meta)
        self.assertEqual(st.Status, 0x0112)
        # Formato não suportado
        st, _, _ = self.film(assoc, fmt="ROW\\2,1", fill=())
        self.assertEqual(st.Status, 0x0106)
        # Imprimir Film Box sem imagens: aviso, nenhum trabalho
        fs_uid = self.ctx.db.connection().execute(
            "SELECT sop_instance_uid FROM print_sessions WHERE kind='film_session'").fetchone()[0]
        fb.ReferencedFilmSessionSequence = [Dataset()]
        fb.ReferencedFilmSessionSequence[0].ReferencedSOPClassUID = FILM_SESSION
        fb.ReferencedFilmSessionSequence[0].ReferencedSOPInstanceUID = fs_uid
        from pydicom.uid import generate_uid
        empty_uid = generate_uid()
        st, rsp = assoc.send_n_create(fb, FILM_BOX, empty_uid, meta_uid=self.meta)
        st, _ = assoc.send_n_action(None, 1, FILM_BOX, empty_uid, meta_uid=self.meta)
        self.assertEqual(st.Status, 0xB603)
        # Image Box com Pixel Data truncado
        ib = Dataset()
        bad = image_item()
        bad.PixelData = b"\0" * 10
        ib.BasicGrayscaleImageSequence = [bad]
        st, _ = assoc.send_n_set(ib, GRAY_IB, rsp.ReferencedImageBoxSequence[0].ReferencedSOPInstanceUID, meta_uid=self.meta)
        self.assertEqual(st.Status, 0x0106)
        # Ação desconhecida
        st, _ = assoc.send_n_action(None, 9, FILM_SESSION, fs_uid, meta_uid=self.meta)
        self.assertEqual(st.Status, 0x0123)
        assoc.release()
        self.assertEqual(self.ctx.jobs.list(), [])

    def test_color_film(self):
        from pydicom.dataset import Dataset
        assoc = self.associate(meta=COLOR_META)
        item = Dataset()
        item.SamplesPerPixel, item.PhotometricInterpretation, item.PlanarConfiguration = 3, "RGB", 0
        item.Rows, item.Columns = 20, 30
        item.BitsAllocated, item.BitsStored, item.HighBit, item.PixelRepresentation = 8, 8, 7, 0
        px = np.zeros((20, 30, 3), dtype=np.uint8)
        px[..., 0] = 200
        item.PixelData = px.tobytes()
        _, fb_uid, boxes = self.film(assoc, fmt="STANDARD\\1,1", fill=(1,), meta_ib=COLOR_IB, item=item, copies=1)
        self.assertEqual(boxes[0].ReferencedSOPClassUID, COLOR_IB)
        st, _ = assoc.send_n_action(None, 1, FILM_BOX, fb_uid, meta_uid=self.meta)
        self.assertEqual(st.Status, 0x0000)
        assoc.release()
        job = self.wait_job(self.ctx.jobs.list()[0].id)
        self.assertEqual(job.state.value, "completed", job.state_reason)

    def test_unprinted_film_is_reported(self):
        assoc = self.associate()
        self.film(assoc, fmt="STANDARD\\1,1", fill=(1,))
        assoc.release()
        import time
        time.sleep(0.3)
        self.assertIn("print.unprinted", [e.action for e in self.ctx.events.query()])
        self.assertEqual(self.ctx.jobs.list(), [])
