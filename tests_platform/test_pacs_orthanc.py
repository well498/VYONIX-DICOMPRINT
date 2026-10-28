"""VYONIX PACS com o Orthanc REAL (núcleo, sem plugins): REST, armazenamento, recuperação idêntica,
reenvio, C-STORE de uma "modalidade" (pynetdicom) seguido de sincronização do índice.

Exige ``VYONIX_TEST_ORTHANC_URL`` (ex.: http://127.0.0.1:8042), ``VYONIX_TEST_ORTHANC_USER``,
``VYONIX_TEST_ORTHANC_PASSWORD`` e ``VYONIX_TEST_ORTHANC_DICOM`` (host:porta:AET). Sem elas o teste
é pulado com motivo explícito — e o CI da plataforma falha em qualquer teste pulado, então lá ele
sempre roda contra um Orthanc instalado pelo pacote da distribuição.
"""

from __future__ import annotations

import os
import time
import unittest

from tests_platform.pacs_support import make_dicom, uid
from tests_platform.support import new_org, require_db

URL = os.environ.get("VYONIX_TEST_ORTHANC_URL", "")


def setUpModule():
    global db
    if not URL:
        raise unittest.SkipTest("VYONIX_TEST_ORTHANC_URL não definida (Orthanc de teste).")
    db = require_db()


class Orthanc(unittest.TestCase):
    def setUp(self):
        from vyonix.pacs.orthanc import OrthancBackend
        self.b = OrthancBackend(URL, username=os.environ.get("VYONIX_TEST_ORTHANC_USER"),
                                password=os.environ.get("VYONIX_TEST_ORTHANC_PASSWORD"))
        self.addCleanup(self.b.close)
        self.t = new_org(db)
        self.n = int(time.time() * 1000) % 10**9          # UIDs novos a cada execução

    def test_ping_reports_version(self):
        info = self.b.ping()
        self.assertEqual(info["name"], "Orthanc")
        self.assertTrue(info["version"])
        print(f"\nOrthanc {info['version']} (API {info['api_version']})")

    def test_wrong_credentials_refused(self):
        from vyonix.pacs.orthanc import OrthancBackend
        bad = OrthancBackend(URL, username="vyonix", password="errada")
        self.addCleanup(bad.close)
        import httpx
        with self.assertRaises(httpx.HTTPStatusError):
            bad.ping()

    def test_store_index_retrieve_identical_and_resend(self):
        from vyonix.pacs import service as pacs
        data = make_dicom(study=uid(self.n, 1), series=uid(self.n, 1, 1), sop=uid(self.n, 1, 1, 1))
        with db.session(self.t) as s:
            r = pacs.ingest(s, self.b, data, actor="teste")
            self.assertTrue(r.new_study)
        with db.session(self.t) as s:
            self.assertEqual(pacs.retrieve_instance(s, self.b, uid(self.n, 1), uid(self.n, 1, 1),
                                                    uid(self.n, 1, 1, 1)), data)
            again = pacs.ingest(s, self.b, data, actor="teste")
            self.assertTrue(again.duplicate)
            md = pacs.metadata(s, self.b, uid(self.n, 1))
            self.assertEqual(md[0]["00080018"]["Value"], [uid(self.n, 1, 1, 1)])

    def test_other_content_same_uids_refused_and_original_intact(self):
        from vyonix.pacs import service as pacs
        a = make_dicom(study=uid(self.n, 2), series=uid(self.n, 2, 1), sop=uid(self.n, 2, 1, 1), fill=1)
        b = make_dicom(study=uid(self.n, 2), series=uid(self.n, 2, 1), sop=uid(self.n, 2, 1, 1), fill=9)
        with db.session(self.t) as s:
            pacs.ingest(s, self.b, a, actor="teste")
        other = new_org(db)
        with db.session(other) as s:
            with self.assertRaises(pacs.InstanceRejected):
                pacs.ingest(s, self.b, b, actor="teste")
        with db.session(self.t) as s:
            self.assertEqual(pacs.retrieve_instance(s, self.b, uid(self.n, 2), uid(self.n, 2, 1),
                                                    uid(self.n, 2, 1, 1)), a)

    def test_cstore_from_modality_then_sync(self):
        from pydicom import dcmread
        from pynetdicom import AE
        import io
        from vyonix.pacs import service as pacs
        host, port, aet = os.environ["VYONIX_TEST_ORTHANC_DICOM"].split(":")
        with db.session(self.t) as s:
            pacs.sync(s, self.b)                            # alinha com o que já estava no motor
        data = make_dicom(study=uid(self.n, 3), series=uid(self.n, 3, 1), sop=uid(self.n, 3, 1, 1), modality="CR")
        ae = AE(ae_title="VYXMODTEST")
        ae.add_requested_context("1.2.840.10008.5.1.4.1.1.2", "1.2.840.10008.1.2.1")
        assoc = ae.associate(host, int(port), ae_title=aet)
        self.assertTrue(assoc.is_established, "associação DICOM recusada pelo Orthanc")
        status = assoc.send_c_store(dcmread(io.BytesIO(data)))
        assoc.release()
        self.assertEqual(status.Status, 0x0000)
        with db.session(self.t) as s:
            out = pacs.sync(s, self.b)
            self.assertGreaterEqual(out["indexed"], 1)
            found = pacs.search_studies(s, {"StudyInstanceUID": uid(self.n, 3)})
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["00080061"]["Value"], ["CR"])
            # origem registrada pelo motor: base do roteamento por AE Title no modo cloud
            from sqlalchemy import select
            from vyonix.pacs.models import PacsInstance
            bid = s.execute(select(PacsInstance.backend_id).where(PacsInstance.sop_uid == uid(self.n, 3, 1, 1))).scalar()
        o = self.b.origin(bid)
        self.assertEqual((o["origin"], o["called_aet"], o["remote_aet"]), ("DicomProtocol", aet, "VYXMODTEST"))

    def test_origin_of_rest_upload(self):
        ref = self.b.store(make_dicom(study=uid(self.n, 4), series=uid(self.n, 4, 1), sop=uid(self.n, 4, 1, 1)))
        o = self.b.origin(ref.backend_id)
        self.assertEqual(o["origin"], "RestApi")
        self.assertIsNone(o["called_aet"])


    def test_backup_and_restore_after_file_lost_in_engine(self):
        """Backup verificado com o Orthanc real; o arquivo some do motor (índice intacto) e a restauração o devolve."""
        import tempfile
        from pathlib import Path
        from vyonix.pacs import backup, service as pacs
        data = make_dicom(study=uid(self.n, 5), series=uid(self.n, 5, 1), sop=uid(self.n, 5, 1, 1), patient_id="BK-ORT")
        with db.session(self.t) as s:
            r = pacs.ingest(s, self.b, data, actor="teste")
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "bkp"
            out = backup.export(db, self.t, self.b, dest)
            self.assertEqual((out["copied"], out["integrity_failures"]), (1, []))
            self.assertTrue(backup.verify(dest)["valid"])
            from sqlalchemy import select
            from vyonix.pacs.models import PacsInstance
            with db.session(self.t) as s:
                bid = s.execute(select(PacsInstance.backend_id).where(PacsInstance.id == r.instance_id)).scalar()
            self.b.delete(bid)                                             # perda do arquivo no motor
            with self.assertRaises(FileNotFoundError):
                self.b.fetch(bid)
            out = backup.restore(db, self.t, self.b, dest)
            self.assertEqual((out["reinstated"], out["rejected"]), (1, []))
        with db.session(self.t) as s:
            self.assertEqual(pacs.retrieve_instance(s, self.b, uid(self.n, 5), uid(self.n, 5, 1),
                                                    uid(self.n, 5, 1, 1)), data)


if __name__ == "__main__":
    unittest.main()
