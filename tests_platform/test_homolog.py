"""Homologação interna: variante da compilação (comercial no repositório; a de homologação libera os módulos e se
identifica), simulador de modalidade (estudo sintético por C-STORE real a um SCP local) e o caminho até a Central
de Exames com o paciente fictício identificado pelo mesmo prontuário. PostgreSQL real; dados sintéticos."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from tests_platform.pacs_support import MemoryBackend
from tests_platform.support import new_org, require_db

ROOT = Path(__file__).resolve().parents[1]


def setUpModule():
    global db
    db = require_db()


class Flavor(unittest.TestCase):
    def test_repository_is_commercial_and_homolog_unlocks_modules(self):
        from vyonix import build_flavor
        self.assertEqual(build_flavor.FLAVOR, "commercial")
        self.assertFalse(build_flavor.HOMOLOG)
        from tests.licensing_support import Computer
        from tests_platform.test_licensing import Base
        h = Base.__new__(Base)
        h.keys = {}
        lic = h.licensing(Computer())
        t = new_org(db)
        with db.session(t) as s:
            self.assertFalse(lic.module_ok(s, "pacs")[0])                    # comercial: sem licença, bloqueado
        with mock.patch.object(build_flavor, "HOMOLOG", True), db.session(t) as s:
            lic._cache.clear()
            ok, msg = lic.module_ok(s, "pacs")
            self.assertTrue(ok)
            self.assertIn("Homologação interna", msg)
            self.assertEqual(lic.status(s)["report"].state, "homologacao")
        lic._cache.clear()

    def test_simulator_refused_in_commercial_build(self):
        from vyonix import cli
        with self.assertRaises(SystemExit):
            cli.main(["homolog-enviar", "--paciente-id", "X", "--nome", "Teste Ficticio"])


class Simulator(unittest.TestCase):
    def test_synthetic_study_by_c_store_reaches_exam_center(self):
        import io

        from pynetdicom import AE, AllStoragePresentationContexts, evt
        from tests_platform.test_pacs_qr import free_port
        from vyonix import homolog
        from vyonix.clinical import service as clinical
        from vyonix.pacs import service as pacs
        from vyonix.ris import prep
        got: list[bytes] = []

        def store(event):
            ds = event.dataset
            ds.file_meta = event.file_meta
            buf = io.BytesIO()
            ds.save_as(buf, enforce_file_format=True)
            got.append(buf.getvalue())
            return 0x0000
        port = free_port()
        ae = AE(ae_title="VYONIX_PACS")
        ae.supported_contexts = AllStoragePresentationContexts
        srv = ae.start_server(("127.0.0.1", port), block=False, evt_handlers=[(evt.EVT_C_STORE, store)])
        self.addCleanup(srv.shutdown)
        with self.assertRaises(ValueError):
            homolog.send([], host="10.0.0.5")                                  # só o computador local
        ds = homolog.synthetic_study(patient_id="HML-001", patient_name="Maria Ficticia", images=3, size=32)
        r = homolog.send(ds, port=port)
        self.assertEqual((r["sent"], r["failed"]), (3, 0))
        t = new_org(db)
        b = MemoryBackend()
        with db.session(t) as s:
            p = clinical.create_patient(s, name="Maria Ficticia", identifiers=[("PRONTUARIO", "HML-001")], actor="t")
            for data in got:
                pacs.ingest(s, b, data, actor="dicom:VYX_SIMULADOR", via="dimse")
            q = prep.queue(s, p.id)
            item = next(x for x in q["items"] if x["study_instance_uid"] == r["study_instance_uid"])
            self.assertEqual((item["images"], item["station"], item["patient_name"]), (3, "SIMULADOR_HML",
                                                                                         "Maria Ficticia"))
            from vyonix.clinical.models import Study
            import uuid
            st = s.get(Study, uuid.UUID(item["study_id"]))
            self.assertEqual(st.patient_id, p.id)                              # vinculado pelo prontuário
        self.assertIn("DADOS SINTETICOS", str(ds[0].PatientComments))


if __name__ == "__main__":
    unittest.main()
