"""TELELAUDO T8 — saídas opcionais do laudo liberado: FHIR R4 DiagnosticReport, HL7 v2 ORU^R01 (com escape) e DICOM
Encapsulated PDF guardado no PACS do VYONIX no mesmo estudo. Plataforma real, PostgreSQL real; motor DUBLÊ DE TESTE
``MemoryBackend``; dados sintéticos."""

from __future__ import annotations

import base64
import io
import unittest
import uuid
from datetime import date

from tests_platform.pacs_support import make_dicom
from tests_platform.support import require_db
from tests_platform.test_pacs import ApiBase


def setUpModule():
    global db
    db = require_db()
    from tests_platform import test_pacs, test_report
    test_pacs.db = test_report.db = db


class Interop(ApiBase):
    def setUp(self):
        super().setUp()
        from vyonix.clinical import service as clinical
        from vyonix.modules import registry
        from vyonix.pacs import service as pacs
        doc = self.helper.issue("annual", modules={"core": {"kind": "contract"}, "report": {"kind": "contract"},
                                                   "pacs": {"kind": "contract"}})
        self.c = self.login()
        with db.session(self.t) as s:
            self.lic.install(s, doc["document"], actor="admin")
            registry.enable(s, "report", actor="admin", license_check=self.lic.module_ok)
            registry.enable(s, "pacs", actor="admin", license_check=self.lic.module_ok)
            self.uid = f"2.25.{uuid.uuid4().int}"
            p = clinical.create_patient(s, name="Interop Sintetica Teste", birth_date=date(1985, 6, 7), sex="F",
                                        identifiers=[("DICOM", "IOP-77")], actor="t")
            o = clinical.create_order(s, patient_id=p.id, requester="Dr. Pedido", actor="t")
            st = clinical.register_study(s, study_instance_uid=self.uid, accession=o.accession, modality="CT",
                                         study_date=date(2026, 10, 28), description="TC de tórax", actor="t")
            clinical.reconcile(s, st.id, o.id, actor="t")
            pacs.ingest(s, self.b, make_dicom(study=self.uid, series=self.uid + ".1", sop=self.uid + ".1.1",
                                              patient_id="IOP-77", patient_name="TESTE^INTEROP"), actor="t")
            self.study = st.id
        uid = self.c.post("/api/v1/users", json={"username": "drio", "display_name": "Dr Io",
                                                  "password": "Senha-Teste-1234", "roles": [{"role": "medico"}]}).json()["id"]
        m = self.login("drio", "Senha-Teste-1234")
        m.post("/api/v1/auth/password", json={"current": "Senha-Teste-1234", "new": "Senha-Nova-9876!"})
        self.med = self.login("drio", "Senha-Nova-9876!")
        pid = self.c.post("/api/v1/report/physicians", json={"user_id": uid, "full_name": "Dr. Io Sintetico",
                                                             "crm": "4242", "crm_uf": "PE"}).json()["id"]
        self.c.post(f"/api/v1/report/physicians/{pid}/links", json={"valid_from": "2026-01-01"})
        rid = self.med.post("/api/v1/report/reports", json={"study_id": str(self.study)}).json()["id"]
        rv = self.med.put(f"/api/v1/report/reports/{rid}", json={"body": "Achados: A|B^C~D&E\\F.\nConclusão: normal."}
                          ).json()["row_version"]
        self.assertEqual(self.med.post(f"/api/v1/report/reports/{rid}/finalize",
                                       json={"password": "Senha-Nova-9876!", "row_version": rv}).status_code, 200)
        self.rid = rid

    def test_fhir_diagnostic_report(self):
        d = self.med.get(f"/api/v1/report/reports/{self.rid}/fhir").json()
        self.assertEqual((d["resourceType"], d["status"], d["code"]["coding"][0]["code"]), ("DiagnosticReport", "final",
                                                                                            "18748-4"))
        self.assertEqual(d["subject"]["identifier"]["value"], "IOP-77")
        self.assertEqual(d["imagingStudy"][0]["identifier"]["value"], f"urn:oid:{self.uid}")
        self.assertEqual(d["resultsInterpreter"][0]["identifier"], {"system": "urn:br:crm:PE", "value": "4242"})
        self.assertTrue(base64.b64decode(d["presentedForm"][0]["data"]).startswith(b"%PDF"))
        self.assertIn("Conclusão: normal.", d["conclusion"])

    def test_hl7_oru_escaping(self):
        r = self.med.get(f"/api/v1/report/reports/{self.rid}/hl7")
        msg = r.content.decode()
        segs = msg.strip("\r").split("\r")
        self.assertEqual([x.split("|")[0] for x in segs][:3], ["MSH", "PID", "OBR"])
        self.assertIn("ORU^R01", segs[0])
        self.assertIn("IOP-77^^^DICOM", segs[1])
        obx = [x for x in segs if x.startswith("OBX|") and "|TX|" in x]
        self.assertIn("A\\F\\B\\S\\C\\R\\D\\T\\E\\E\\F.", obx[0])           # delimitadores escapados
        self.assertEqual(obr_field(segs[2], 25), "F")
        self.assertTrue(obr_field(segs[2], 32).startswith("4242&Dr. Io Sintetico"))

    def test_send_to_pacs_as_encapsulated_pdf(self):
        from pydicom import dcmread
        r = self.med.post(f"/api/v1/report/reports/{self.rid}/send-to-pacs")
        self.assertEqual(r.status_code, 200, r.text)
        out = r.json()
        self.assertTrue(out["sop_instance_uid"].startswith("2.25."))
        data = next(v for v in self.b.files.values() if out["sop_instance_uid"].encode() in v)
        ds = dcmread(io.BytesIO(data))
        self.assertEqual((ds.SOPClassUID, ds.StudyInstanceUID, ds.PatientID, ds.Modality),
                         ("1.2.840.10008.5.1.4.1.1.104.1", self.uid, "IOP-77", "DOC"))
        self.assertTrue(bytes(ds.EncapsulatedDocument).startswith(b"%PDF"))
        series = self.c.get(f"/api/v1/pacs/dicomweb/studies/{self.uid}/series").json()
        self.assertEqual(len(series), 2)                                    # imagens + laudo no mesmo estudo


def obr_field(seg: str, n: int) -> str:
    return seg.split("|")[n]


if __name__ == "__main__":
    unittest.main()
