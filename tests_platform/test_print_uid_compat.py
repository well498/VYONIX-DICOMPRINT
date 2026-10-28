"""BKL-10 — compatibilidade: imagem Secondary Capture criada pelo DICOM Print (UIDs 2.25.<UUID>) é aceita pela
entrada do VYONIX PACS com os UIDs inalterados. PostgreSQL real; motor DUBLÊ DE TESTE ``MemoryBackend``; dados
sintéticos. (O Print não encaminha ao PACS nesta versão: o teste cobre um encaminhamento futuro ou uma importação.)"""

from __future__ import annotations

import unittest

from tests_platform.pacs_support import MemoryBackend
from tests_platform.support import new_org, require_db

try:
    import numpy as np
    HAS = True
except ImportError:
    HAS = False


def setUpModule():
    global db
    db = require_db()


@unittest.skipUnless(HAS, "numpy não instalado")
class PrintToPacs(unittest.TestCase):
    def test_print_secondary_capture_accepted_by_pacs(self):
        from pydicom import dcmread
        import io
        from app.dicom.print_intake import _sc_dataset
        from app.dicom.uids import new_uid
        from vyonix.pacs import service as pacs
        t = new_org(db)
        b = MemoryBackend()
        study, series = new_uid(), new_uid()
        data = _sc_dataset(np.full((32, 48), 128, dtype=np.uint8), study, series, 1, "CR_PRINT")
        ds = dcmread(io.BytesIO(data))
        self.assertTrue(ds.SOPInstanceUID.startswith("2.25."))
        with db.session(t) as s:
            # Como sai do Print (sem dados do paciente, por projeto): o PACS recusa pela falta do Patient ID —
            # nunca pelos UIDs. Igual antes e depois do BKL-10.
            with self.assertRaises(pacs.InstanceRejected) as cm:
                pacs.ingest(s, b, data, actor="teste", via="stow")
            self.assertIn("Patient ID", str(cm.exception))
        ds.PatientID, ds.PatientName = "SINT-001", "TESTE^SINTETICO"     # importação identificada (simulada)
        buf = io.BytesIO()
        ds.save_as(buf, enforce_file_format=True)
        data = buf.getvalue()
        with db.session(t) as s:
            r = pacs.ingest(s, b, data, actor="teste", via="stow")
            self.assertFalse(r.duplicate)
            again = pacs.ingest(s, b, data, actor="teste", via="stow")
            self.assertTrue(again.duplicate)
            st = pacs.stats(s)
        self.assertEqual(st["instances"], 1)
        self.assertIn(data, b.files.values())                  # guardado byte a byte
        with db.session(t) as s:
            from sqlalchemy import select
            from vyonix.pacs.models import PacsInstance
            self.assertEqual(s.execute(select(PacsInstance.sop_uid)).scalar_one(), ds.SOPInstanceUID)


if __name__ == "__main__":
    unittest.main()
