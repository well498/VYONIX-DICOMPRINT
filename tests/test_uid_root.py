"""BKL-10 (branch de correção): UIDs gerados pelo Print usam ``2.25.<UUID>`` e nenhum usa a raiz do pydicom.

Complementa ``tests/test_uid_handling.py`` (comportamento preservado), que roda igual antes e depois da correção.
"""

import re
import time
import unittest
from pathlib import Path

from tests.helpers import TempDirTestCase

try:
    import numpy as np  # noqa: F401
    import pynetdicom  # noqa: F401
    HAS = True
except ImportError:
    HAS = False

FORMAT = re.compile(r"^2\.25\.(0|[1-9][0-9]*)$")
PYDICOM_ROOT = "1.2.826.0.1.3680043.8.498"
APP = Path(__file__).resolve().parents[1] / "app"


class Generator(unittest.TestCase):
    def test_format_length_uniqueness(self):
        from app.dicom.uids import is_strict, new_uid
        many = [new_uid() for _ in range(50000)]
        self.assertEqual(len(set(many)), len(many))
        for u in many[:2000]:
            self.assertRegex(u, FORMAT)
            self.assertTrue(is_strict(u))
            self.assertLessEqual(len(u), 44)

    def test_conformance_ps3_5(self):
        """§9.1 (sintaxe, 64 caracteres), §B.2 (2.25 + inteiro decimal do UUID de 128 bits, sem zero à esquerda) e a
        validação independente do pydicom."""
        import uuid as uuidlib
        from pydicom.uid import UID
        from app.dicom.uids import new_uid
        for _ in range(5000):
            u = new_uid()
            n = u[len("2.25."):]
            self.assertTrue(u.startswith("2.25."))
            self.assertTrue(n == "0" or not n.startswith("0"))
            self.assertLess(int(n), 2 ** 128)
            self.assertEqual(uuidlib.UUID(int=int(n)).version, 4)          # UUID aleatório (RFC 9562), não sequencial
            self.assertTrue(UID(u).is_valid, u)
            self.assertLessEqual(len(u), 64)

    def test_is_strict(self):
        from app.dicom.uids import is_strict
        for good in ("1.2.840.10008.5.1.4.1.1.7", "2.25.0", "1.0.3"):
            self.assertTrue(is_strict(good), good)
        for bad in ("", "1.02.3", "1..2", "1.2.", "a.1", "1." + "2" * 70):
            self.assertFalse(is_strict(bad), bad)

    def test_no_foreign_root_in_application_code(self):
        offenders = []
        for p in APP.rglob("*.py"):
            text = p.read_text(encoding="utf-8")
            if p.name != "uids.py" and (PYDICOM_ROOT in text or "generate_uid(" in text):
                offenders.append(str(p.relative_to(APP)))
        self.assertEqual(offenders, [])


@unittest.skipUnless(HAS, "numpy/pynetdicom não instalados")
class PrintFlow(TempDirTestCase):
    def test_all_generated_uids_use_uuid_root_and_received_ones_are_kept(self):
        from tests.test_print_scp import FILM_BOX, PrintSCPTest
        h = PrintSCPTest("test_printer_status_and_full_film_to_pdf")
        h.setUp()
        self.addCleanup(h.tearDown)
        assoc = h.associate()
        st, fb_uid, boxes = h.film(assoc)          # o equipamento informa os UIDs de Film Session e Film Box
        self.assertEqual(st.Status, 0x0000)
        self.assertFalse(fb_uid.startswith("2.25."))
        for b in boxes:                            # Image Box: criados pelo SCP
            self.assertRegex(b.ReferencedSOPInstanceUID, FORMAT)
        st, _ = assoc.send_n_action(None, 1, FILM_BOX, fb_uid, meta_uid=h.meta)
        self.assertEqual(st.Status, 0x0000)
        assoc.release()
        end = time.monotonic() + 30
        rows = []
        while time.monotonic() < end and len(rows) < 3:
            rows = h.ctx.db.connection().execute(
                "SELECT sop_instance_uid, study_uid, series_uid, sop_class_uid FROM instances "
                "WHERE source_ae = 'CR_PRINT'").fetchall()
            time.sleep(0.1)
        self.assertEqual(len(rows), 3)
        for sop, study, series, cls in rows:
            for u in (sop, study, series):
                self.assertRegex(u, FORMAT)
            self.assertEqual(cls, "1.2.840.10008.5.1.4.1.1.7")
        job = h.wait_job(h.ctx.jobs.list()[0].id)
        self.assertEqual(job.state.value, "completed", job.state_reason)

    def test_previously_stored_objects_untouched(self):
        """Objetos já guardados com a raiz antiga não são reescritos; reenvio continua detectado como duplicata."""
        import hashlib
        from app.core.contracts import AssociationPeer
        from tests.dicom_helpers import make_ct
        from tests.test_print_scp import FILM_BOX, PrintSCPTest
        h = PrintSCPTest("test_printer_status_and_full_film_to_pdf")
        h.setUp()
        self.addCleanup(h.tearDown)
        old = "1.2.826.0.1.3680043.8.498.112233445566778899001122334455"      # 56 caracteres
        data = make_ct(self.tmp / "antigo.dcm", sop_uid=old, study_uid=old[:-2] + "1", series_uid=old[:-2] + "2").read_bytes()
        peer = AssociationPeer("CT_ANTIGO", "VYONIX", "127.0.0.1", 104)
        first = h.ctx.store.store(data, peer, None, max_bytes=10 ** 8)
        self.assertIsNotNone(first.instance, first.message)
        digest = hashlib.sha256(first.instance.file_path.read_bytes()).hexdigest()
        assoc = h.associate()
        st, fb_uid, _ = h.film(assoc)
        assoc.send_n_action(None, 1, FILM_BOX, fb_uid, meta_uid=h.meta)
        assoc.release()
        h.wait_job(h.ctx.jobs.list()[0].id)
        row = h.ctx.db.connection().execute("SELECT sop_instance_uid, study_uid, file_path FROM instances "
                                            "WHERE sop_instance_uid = ?", (old,)).fetchone()
        self.assertEqual(row["study_uid"], old[:-2] + "1")
        self.assertEqual(hashlib.sha256(Path(row["file_path"]).read_bytes()).hexdigest(), digest)
        self.assertTrue(h.ctx.store.store(data, peer, None, max_bytes=10 ** 8).duplicate)

    def test_selftest_image_uses_uuid_root(self):
        from app.imaging import selftest
        ds, _ = selftest._dataset(self.tmp / "selftest.dcm")
        for u in (ds.SOPInstanceUID, ds.StudyInstanceUID, ds.SeriesInstanceUID):
            self.assertRegex(u, FORMAT)


if __name__ == "__main__":
    unittest.main()
