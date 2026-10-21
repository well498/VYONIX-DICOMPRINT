"""Fase 4 — envio real ao spooler do Windows (executa só no Windows, no pipeline de CI).

Usa a impressora "Microsoft Print to PDF" (driver do próprio Windows) para verificar, sem
papel, o caminho completo DEVMODE → GDI → spooler → arquivo. Se ela não estiver instalada, o
teste é ignorado com o motivo — nunca é simulado.
"""

import sys
import time
import unittest

from tests.helpers import TempDirTestCase


@unittest.skipUnless(sys.platform == "win32", "somente no Windows")
class WindowsPrintingTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        from app.printing.backends.windows import WindowsPrinterBackend, available
        ok, why = available()
        if not ok:
            self.fail(f"pywin32 deveria estar disponível no Windows: {why}")
        self.backend = WindowsPrinterBackend(self.tmp / "auto")

    def ms_pdf(self):
        printers = self.backend.list_printers()
        self.assertIsInstance(printers, list)
        p = next((p for p in printers if "print to pdf" in p.driver.lower()), None)
        if p is None:
            self.skipTest("Microsoft Print to PDF não instalada neste Windows: "
                          + ", ".join(x.name for x in printers))
        return p

    def test_list_reports_capabilities(self):
        p = self.ms_pdf()
        self.assertTrue(p.port)
        self.assertTrue(any("A4" in n for n in p.paper_sizes), p.paper_sizes)

    def test_submit_two_pages_creates_file(self):
        import numpy as np
        from app.core.contracts import ComposedPage, SpoolRequest
        p = self.ms_pdf()

        def pages():
            for i in range(2):
                px = np.full((1169, 827), 255, dtype=np.uint8)   # A4 a 100 dpi
                px[100:400, 100:400] = 0
                yield ComposedPage(index=i, pixels=px, dpi=100)

        req = SpoolRequest(printer=p.name, document_name="VYONIX-teste-ci", pages=pages, page_count=2, copies=1,
                           paper="A4", width_mm=210.0, height_mm=297.0, orientation="portrait", dpi=100)
        result = self.backend.submit(req)
        self.assertTrue(result.accepted, result.error)
        self.assertFalse(result.confirmed)        # aceito pelo spooler ≠ impresso
        self.assertTrue(result.output_path)
        from pathlib import Path
        out = Path(result.output_path)
        for _ in range(150):
            if out.exists() and out.stat().st_size > 0:
                break
            time.sleep(0.2)
        self.assertTrue(out.exists() and out.stat().st_size > 1000, result.detail)
        if result.spool_job_id:
            st = self.backend.job_status(p.name, result.spool_job_id)
            self.assertIn(st.state, ("queued", "printing", "printed", "gone"))
