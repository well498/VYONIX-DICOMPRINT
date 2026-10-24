"""VYONIX PACS — primeira entrega vertical: receber, validar, armazenar, indexar, pesquisar, recuperar,
abrir (metadados e frames), auditar; isolamento entre organizações; DICOMweb pela API.

Banco PostgreSQL real. O motor é o DUBLÊ DE TESTE ``MemoryBackend`` (ver ``pacs_support``); a
integração com o Orthanc real está em ``test_pacs_orthanc.py``. Dados DICOM sintéticos.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

from tests_platform.pacs_support import MemoryBackend, make_dicom, uid
from tests_platform.support import ADMIN_PW, new_org, require_db


def setUpModule():
    global db
    db = require_db()


def _audit(s, action):
    from sqlalchemy import select
    from vyonix.audit.models import AuditEntry
    return list(s.execute(select(AuditEntry).where(AuditEntry.action == action)).scalars())


class Ingest(unittest.TestCase):
    def setUp(self):
        self.t = new_org(db)
        self.b = MemoryBackend()

    def ingest(self, data, tenant=None, **kw):
        """Como o STOW-RS e a sincronização: a recusa é capturada dentro da transação, que é confirmada
        (a auditoria da recusa fica gravada) e a exceção segue para o teste."""
        from vyonix.pacs import service as pacs
        err = None
        with db.session(tenant or self.t) as s:
            try:
                return pacs.ingest(s, self.b, data, actor="teste", **kw)
            except pacs.InstanceRejected as exc:
                err = exc
        raise err

    def test_receive_validate_store_index_link_audit_event(self):
        from sqlalchemy import select
        from vyonix.clinical.models import Study
        from vyonix.events.models import OutboxEvent
        from vyonix.pacs.models import PacsInstance, PacsSeries, PacsStudy
        data = make_dicom(accession="ACC1")
        r = self.ingest(data)
        self.assertTrue(r.new_study)
        self.assertFalse(r.duplicate)
        with db.session(self.t) as s:
            st = s.execute(select(PacsStudy)).scalar_one()
            self.assertEqual((st.study_uid, st.patient_id, st.accession), (uid(1), "PAC-0001", "ACC1"))
            self.assertEqual(str(st.study_date), "2026-10-20")
            se = s.execute(select(PacsSeries)).scalar_one()
            self.assertEqual(se.modality, "CT")
            it = s.execute(select(PacsInstance)).scalar_one()
            self.assertEqual(it.sha256, hashlib.sha256(data).hexdigest())
            self.assertEqual(self.b.files[it.backend_id], data)                 # guardado sem alteração
            cs = s.get(Study, st.clinical_study_id)
            self.assertEqual((cs.study_instance_uid, cs.accession, cs.modality), (uid(1), "ACC1", "CT"))
            self.assertEqual(len(_audit(s, "pacs.instance.store")), 1)
            ev = s.execute(select(OutboxEvent).where(OutboxEvent.type == "pacs.study.received.v1")).scalar_one()
            self.assertNotIn("TESTE", str(ev.data))                              # sem dados do paciente
            self.assertNotIn("PAC-0001", str(ev.data))

    def test_resend_is_idempotent(self):
        data = make_dicom()
        self.ingest(data)
        r = self.ingest(data)
        self.assertTrue(r.duplicate)
        from sqlalchemy import func, select
        from vyonix.pacs.models import PacsInstance
        with db.session(self.t) as s:
            self.assertEqual(s.execute(select(func.count()).select_from(PacsInstance)).scalar(), 1)

    def test_same_sop_with_other_content_is_refused_and_audited(self):
        from vyonix.pacs.service import InstanceRejected
        self.ingest(make_dicom(fill=1))
        with self.assertRaises(InstanceRejected):
            self.ingest(make_dicom(fill=2))
        with db.session(self.t) as s:
            self.assertEqual(len(_audit(s, "pacs.instance.reject")), 1)

    def test_invalid_objects_refused(self):
        from vyonix.pacs.service import InstanceRejected
        for bad in (b"", b"nao e dicom" * 20, make_dicom()[:200]):
            with self.assertRaises(InstanceRejected):
                self.ingest(bad)
        with self.assertRaises(InstanceRejected) as cm:
            self.ingest(make_dicom(patient_id=""))
        self.assertIn("Patient ID", str(cm.exception))
        with self.assertRaises(InstanceRejected):
            self.ingest(make_dicom(sop="1.2.abc"))
        self.assertEqual(self.b.files, {})                                      # nada chegou ao motor
        with db.session(self.t) as s:
            self.assertEqual(len(_audit(s, "pacs.instance.reject")), 5)

    def test_instance_of_other_patient_in_same_study_refused_and_engine_rolled_back(self):
        from vyonix.pacs.service import InstanceRejected
        self.ingest(make_dicom())
        other = make_dicom(sop=uid(1, 1, 2), patient_id="PAC-9999")
        with self.assertRaises(InstanceRejected):
            self.ingest(other)
        self.assertEqual(len(self.b.files), 1)                                  # o motor foi desfeito
        self.assertEqual(len(self.b.deleted), 1)

    def test_engine_down_leaves_nothing_indexed(self):
        from sqlalchemy import func, select
        from vyonix.pacs.backend import BackendUnavailable
        from vyonix.pacs.models import PacsStudy
        self.b.down = True
        with self.assertRaises(BackendUnavailable):
            self.ingest(make_dicom())
        with db.session(self.t) as s:
            self.assertEqual(s.execute(select(func.count()).select_from(PacsStudy)).scalar(), 0)

    def test_tenant_isolation(self):
        from vyonix.pacs import service as pacs
        from vyonix.errors import NotFound
        other = new_org(db)
        self.ingest(make_dicom())
        with db.session(other) as s:
            self.assertEqual(pacs.search_studies(s, {}), [])
            with self.assertRaises(NotFound):
                pacs.retrieve_instance(s, self.b, uid(1), uid(1, 1), uid(1, 1, 1))
        # Outra organização com os mesmos UIDs e o mesmo Patient ID, mas outro conteúdo: o motor
        # (compartilhado) já tem a instância; a entrada é recusada e o arquivo da primeira fica intacto.
        original = dict(self.b.files)
        with self.assertRaises(pacs.InstanceRejected):
            self.ingest(make_dicom(fill=7), tenant=other)
        self.assertEqual(self.b.files, original)
        # Mesmo conteúdo enviado pela outra organização: aceito no índice dela, sem duplicar no motor.
        r = self.ingest(make_dicom(), tenant=other)
        self.assertFalse(r.duplicate)
        self.assertEqual(len(self.b.files), 1)
        with db.session(other) as s:
            self.assertEqual(len(pacs.search_studies(s, {})), 1)

    def test_sync_indexes_cstore_arrivals(self):
        from vyonix.pacs import service as pacs
        self.b.receive_cstore(make_dicom())
        self.b.receive_cstore(make_dicom(sop=uid(1, 1, 2), instance_number=2))
        self.b.receive_cstore(make_dicom(patient_id=""))          # chega ao motor, mas é recusada no índice
        with db.session(self.t) as s:
            out = pacs.sync(s, self.b)
        self.assertEqual(out, {"indexed": 2, "duplicates": 0, "rejected": 1})
        with db.session(self.t) as s:
            out = pacs.sync(s, self.b)
            self.assertEqual(out["indexed"], 0)                    # continua do último seq
            self.assertEqual(len(pacs.search_instances(s, uid(1))), 2)
            self.assertTrue(all(a.details["via"] == "dimse" for a in _audit(s, "pacs.instance.store")))


class QueryRetrieve(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from vyonix.pacs import service as pacs
        cls.t = new_org(db)
        cls.b = MemoryBackend()
        cls.data = {
            "a1": make_dicom(),
            "a2": make_dicom(sop=uid(1, 1, 2), instance_number=2, fill=50),
            "mf": make_dicom(series=uid(1, 2), sop=uid(1, 2, 1), frames=3, series_number=2),
            "b": make_dicom(study=uid(2), series=uid(2, 1), sop=uid(2, 1, 1), patient_id="PAC-0002",
                            patient_name="OUTRO^PACIENTE", modality="CR", study_date="20250101", accession="X9"),
            "jp": make_dicom(study=uid(3), series=uid(3, 1), sop=uid(3, 1, 1), patient_id="PAC-0003",
                             modality="XA", encapsulated=[b"\xff\xd8frame-um\xff\xd9", b"\xff\xd8frame-dois\xff\xd9"]),
        }
        with db.session(cls.t) as s:
            for d in cls.data.values():
                pacs.ingest(s, cls.b, d, actor="teste")

    def s(self):
        return db.session(self.t)

    def test_qido_filters(self):
        from vyonix.pacs import service as pacs
        with self.s() as s:
            self.assertEqual(len(pacs.search_studies(s, {})), 3)
            r = pacs.search_studies(s, {"PatientName": "outro*"})
            self.assertEqual([x["0020000D"]["Value"][0] for x in r], [uid(2)])
            self.assertEqual(len(pacs.search_studies(s, {"PatientName": "TESTE"})), 2)       # prefixo
            self.assertEqual(len(pacs.search_studies(s, {"StudyDate": "20260101-20261231"})), 2)
            self.assertEqual(len(pacs.search_studies(s, {"ModalitiesInStudy": "CR"})), 1)
            self.assertEqual(len(pacs.search_studies(s, {"AccessionNumber": "X9"})), 1)
            self.assertEqual(len(pacs.search_studies(s, {"PatientID": "PAC-000*"})), 3)
            self.assertEqual(len(pacs.search_studies(s, {"PatientName": "%"})), 0)          # % não é curinga
            self.assertEqual(len(pacs.search_studies(s, {}, limit=1, offset=1)), 1)
            a = next(x for x in pacs.search_studies(s, {"StudyInstanceUID": uid(1)}))
            self.assertEqual(a["00201206"]["Value"], [2])            # séries
            self.assertEqual(a["00201208"]["Value"], [3])            # instâncias
            self.assertEqual(a["00080061"]["Value"], ["CT"])
            self.assertEqual(len(pacs.search_series(s, uid(1))), 2)
            self.assertEqual(len(pacs.search_instances(s, uid(1), uid(1, 1))), 2)

    def test_bad_date_is_validation_error(self):
        from vyonix.errors import ValidationFailed
        from vyonix.pacs import service as pacs
        with self.s() as s, self.assertRaises(ValidationFailed):
            pacs.search_studies(s, {"StudyDate": "2026-10"})

    def test_retrieve_is_byte_identical_and_verified(self):
        from vyonix.errors import Conflict
        from vyonix.pacs import service as pacs
        with self.s() as s:
            self.assertEqual(pacs.retrieve_instance(s, self.b, uid(1), uid(1, 1), uid(1, 1, 2)), self.data["a2"])
            self.assertEqual(len(list(pacs.retrieve_many(s, self.b, uid(1)))), 3)
        # corrupção no motor é detectada na recuperação
        bid = next(k for k, v in self.b.files.items() if v == self.data["a1"])
        self.b.files[bid] = self.data["a1"][:-1] + bytes([self.data["a1"][-1] ^ 0xFF])
        try:
            with self.s() as s, self.assertRaises(Conflict) as cm:
                pacs.retrieve_instance(s, self.b, uid(1), uid(1, 1), uid(1, 1, 1))
            self.assertEqual(cm.exception.code, "integrity")
        finally:
            self.b.files[bid] = self.data["a1"]

    def test_metadata_has_no_pixels_and_points_to_frames(self):
        from vyonix.pacs import service as pacs
        with self.s() as s:
            md = pacs.metadata(s, self.b, uid(1), base_url="https://x/dw")
        self.assertEqual(len(md), 3)
        one = md[0]
        self.assertNotIn("Value", one["7FE00010"])
        self.assertNotIn("InlineBinary", one["7FE00010"])
        self.assertTrue(one["7FE00010"]["BulkDataURI"].endswith("/frames/1"))
        self.assertEqual(one["00100020"]["Value"], ["PAC-0001"])
        self.assertEqual(one["00280010"]["Value"], [4])

    def test_frames_native_and_encapsulated(self):
        from vyonix.errors import NotFound
        from vyonix.pacs import service as pacs
        with self.s() as s:
            media, ts, fr = pacs.frames(s, self.b, uid(1), uid(1, 2), uid(1, 2, 1), [1, 3])
            self.assertEqual((media, ts), ("application/octet-stream", "1.2.840.10008.1.2.1"))
            self.assertEqual([len(f) for f in fr], [32, 32])                     # 4x4x16 bits
            self.assertEqual(int.from_bytes(fr[1][:2], "little"), 200)           # frame 3 começa em 200
            media, ts, fr = pacs.frames(s, self.b, uid(3), uid(3, 1), uid(3, 1, 1), [2])
            self.assertEqual((media, ts), ("image/jpeg", "1.2.840.10008.1.2.4.50"))
            self.assertEqual(fr, [b"\xff\xd8frame-dois\xff\xd9"])
            with self.assertRaises(NotFound):
                pacs.frames(s, self.b, uid(1), uid(1, 2), uid(1, 2, 1), [4])

    def test_open_study_is_audited(self):
        from vyonix.pacs import service as pacs
        with self.s() as s:
            pacs.open_study(s, uid(2), actor="medico")
            self.assertTrue(any(a.actor == "medico" for a in _audit(s, "pacs.study.open")))


class Api(unittest.TestCase):
    """DICOMweb pela API HTTP: autenticação, permissão, módulo/licença, STOW, QIDO e WADO."""

    def setUp(self):
        from fastapi.testclient import TestClient
        from tests.licensing_support import Computer, make_manager
        from tests_platform.test_licensing import Base
        from vyonix.api.app import create_app
        from vyonix.config import Config
        from vyonix.context import build
        self.tmp = Path(tempfile.mkdtemp(prefix="vyx-pacs-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.pc = Computer()
        self.lm, self.lm_admin, self.keys, self.cid = make_manager(self.tmp / "lm", clock=lambda: self.pc.clock.wall)
        self.addCleanup(self.lm.close)
        self.helper = Base.__new__(Base)
        self.helper.keys, self.helper.lm, self.helper.admin, self.helper.cid = self.keys, self.lm, self.lm_admin, self.cid
        self.lic = self.helper.licensing(self.pc)
        self.helper.lic = self.lic
        self.code = f"pacs-{self.id().split('.')[-1][:20].replace('_', '-')}"
        self.t = new_org(db, self.code)
        self.b = MemoryBackend()
        cfg = Config(data_dir=self.tmp / "data", default_organization=self.code)
        self.plat = build(cfg, licensing=self.lic, db=db)
        self.plat.options["pacs_backend"] = self.b
        self.client = TestClient(create_app(self.plat, cookie_secure=False))

    def license_and_enable(self):
        lic = self.helper.issue("annual", modules={"core": {"kind": "contract"}, "pacs": {"kind": "contract"}})
        with db.session(self.t) as s:
            self.lic.install(s, lic["document"], actor="admin")
        r = self.c.post("/api/v1/modules/pacs/enable")
        self.assertIn(r.status_code, (200, 204), r.text)

    def login(self, user="admin", pw=ADMIN_PW):
        from fastapi.testclient import TestClient
        c = TestClient(self.client.app)
        r = c.post("/api/v1/auth/login", json={"username": user, "password": pw})
        self.assertEqual(r.status_code, 200, r.text)
        c.headers["X-CSRF-Token"] = r.json()["csrf"]
        return c

    @staticmethod
    def stow_body(*items: bytes) -> tuple[bytes, str]:
        from vyonix.api.routes_pacs import multipart
        return multipart(items, "application/dicom")

    @staticmethod
    def parts(resp) -> list[bytes]:
        from vyonix.api.routes_pacs import parse_multipart
        return parse_multipart(resp.content, resp.headers["content-type"])

    def test_vertical_slice_over_dicomweb(self):
        self.c = self.login()
        DW = "/api/v1/pacs/dicomweb"
        body, ctype = self.stow_body(make_dicom())
        r = self.c.post(DW + "/studies", content=body, headers={"Content-Type": ctype})
        self.assertEqual((r.status_code, r.json()["error"]), (402, "module_disabled"))
        self.license_and_enable()
        a1, a2, bad = make_dicom(), make_dicom(sop=uid(1, 1, 2), instance_number=2), b"lixo"
        body, ctype = self.stow_body(a1, a2, bad)
        r = self.c.post(DW + "/studies", content=body, headers={"Content-Type": ctype})
        self.assertEqual(r.status_code, 202, r.text)                    # parte aceita, parte recusada
        j = r.json()
        self.assertEqual(r.headers["content-type"], "application/dicom+json")
        self.assertEqual(len(j["00081199"]["Value"]), 2)
        self.assertEqual(len(j["00081198"]["Value"]), 1)
        self.assertIn("X-Vyonix-Failures", r.headers)
        # CSRF continua exigido
        tok = self.c.headers.pop("X-CSRF-Token")
        self.assertEqual(self.c.post(DW + "/studies", content=body, headers={"Content-Type": ctype}).status_code, 403)
        self.c.headers["X-CSRF-Token"] = tok
        # QIDO
        r = self.c.get(DW + "/studies", params={"PatientID": "PAC-0001"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()[0]["0020000D"]["Value"], [uid(1)])
        self.assertEqual(self.c.get(DW + "/studies", params={"PatientID": "NINGUEM"}).status_code, 204)
        self.assertEqual(len(self.c.get(f"{DW}/studies/{uid(1)}/series").json()), 1)
        self.assertEqual(len(self.c.get(f"{DW}/studies/{uid(1)}/series/{uid(1, 1)}/instances").json()), 2)
        # WADO: estudo inteiro, instância, metadados, frames
        r = self.c.get(f"{DW}/studies/{uid(1)}")
        self.assertEqual(sorted(self.parts(r)), sorted([a1, a2]))
        r = self.c.get(f"{DW}/studies/{uid(1)}/series/{uid(1, 1)}/instances/{uid(1, 1, 2)}")
        self.assertEqual(self.parts(r), [a2])
        md = self.c.get(f"{DW}/studies/{uid(1)}/metadata").json()
        self.assertTrue(md[0]["7FE00010"]["BulkDataURI"].startswith("http"))
        r = self.c.get(f"{DW}/studies/{uid(1)}/series/{uid(1, 1)}/instances/{uid(1, 1, 1)}/frames/1")
        self.assertEqual(r.status_code, 200)
        self.assertIn('type="application/octet-stream"', r.headers["content-type"])
        self.assertEqual(len(self.parts_any(r)[0]), 32)
        self.assertEqual(self.c.get(f"{DW}/studies/{uid(9)}/metadata").status_code, 404)
        # estado e auditoria de abertura
        st = self.c.get("/api/v1/pacs/status").json()
        self.assertEqual((st["index"]["instances"], st["engine"]["reachable"]), (2, True))
        with db.session(self.t) as s:
            self.assertGreaterEqual(len(_audit(s, "pacs.study.open")), 2)

    def parts_any(self, resp) -> list[bytes]:
        ct = resp.headers["content-type"]
        boundary = ct.split("boundary=")[1].split(";")[0]
        chunks = resp.content.split(b"--" + boundary.encode())[1:-1]
        return [c.split(b"\r\n\r\n", 1)[1][:-2] for c in chunks]

    def test_permissions_and_read_without_license(self):
        self.c = self.login()
        self.license_and_enable()
        body, ctype = self.stow_body(make_dicom())
        self.assertEqual(self.c.post("/api/v1/pacs/dicomweb/studies", content=body,
                                     headers={"Content-Type": ctype}).status_code, 200)
        r = self.c.post("/api/v1/users", json={"username": "recep", "display_name": "Recepção",
                                               "password": "Recepcao-1234", "roles": [{"role": "recepcionista"}]})
        self.assertEqual(r.status_code, 201, r.text)
        rc = self.login("recep", "Recepcao-1234")
        self.assertEqual(rc.get("/api/v1/pacs/dicomweb/studies").status_code, 403)
        # módulo desabilitado: dados existentes continuam pesquisáveis e recuperáveis; entrada recusada
        r = self.c.post("/api/v1/modules/pacs/disable", json={"reason": "teste"})
        self.assertIn(r.status_code, (200, 204), r.text)
        self.assertEqual(self.c.get("/api/v1/pacs/dicomweb/studies").status_code, 200)
        self.assertEqual(self.c.get(f"/api/v1/pacs/dicomweb/studies/{uid(1)}").status_code, 200)
        body, ctype = self.stow_body(make_dicom(sop=uid(1, 1, 5)))
        self.assertEqual(self.c.post("/api/v1/pacs/dicomweb/studies", content=body,
                                     headers={"Content-Type": ctype}).status_code, 402)

    def test_engine_not_configured_or_down(self):
        self.c = self.login()
        self.license_and_enable()
        self.b.down = True
        body, ctype = self.stow_body(make_dicom())
        r = self.c.post("/api/v1/pacs/dicomweb/studies", content=body, headers={"Content-Type": ctype})
        self.assertEqual((r.status_code, r.json()["error"]), (503, "unavailable"))
        self.assertFalse(self.c.get("/api/v1/pacs/status").json()["engine"]["reachable"])
        self.plat.options.pop("pacs_backend")
        self.assertEqual(self.c.get(f"/api/v1/pacs/dicomweb/studies/{uid(1)}").status_code, 503)


if __name__ == "__main__":
    unittest.main()
