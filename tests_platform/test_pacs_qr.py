"""Consulta/recuperação DICOM do PACS pelo Core (C-FIND/C-MOVE, Study Root), com associações DICOM reais
(pynetdicom dos dois lados: estação que consulta e estação de destino do C-MOVE), PostgreSQL real e o motor DUBLÊ DE
TESTE ``MemoryBackend``. Dados sintéticos.

Cenários: AE desconhecido e IP divergente recusados; AE chamado errado; C-FIND nos níveis estudo/série/imagem;
C-MOVE para destino não cadastrado (0xA801) e cadastrado (arquivos idênticos aos recebidos); integridade violada no
motor (instância não enviada); isolamento no modo cloud (nó de uma organização chamando o AE de outra); auditoria.
"""

from __future__ import annotations

import hashlib
import secrets
import shutil
import socket
import tempfile
import threading
import unittest
from pathlib import Path

from tests_platform.pacs_support import MemoryBackend, make_dicom, uid
from tests_platform.support import new_org, require_db


def setUpModule():
    global db
    db = require_db()
    try:
        import pynetdicom  # noqa: F401
    except ImportError as exc:
        raise unittest.SkipTest(f"pynetdicom ausente: {exc}")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Receiver:
    """Estação de destino do C-MOVE (Storage SCP real do pynetdicom)."""

    def __init__(self, ae_title: str) -> None:
        from pynetdicom import AE, AllStoragePresentationContexts, evt
        from pynetdicom.sop_class import Verification
        self.received: dict[str, bytes] = {}
        self.port = free_port()
        ae = AE(ae_title=ae_title)
        ae.supported_contexts = AllStoragePresentationContexts
        ae.add_supported_context(Verification)
        self.lock = threading.Lock()
        self.server = ae.start_server(("127.0.0.1", self.port), block=False,
                                      evt_handlers=[(evt.EVT_C_STORE, self._store)])

    def _store(self, event):
        ds = event.dataset
        ds.file_meta = event.file_meta
        with self.lock:
            self.received[str(ds.SOPInstanceUID)] = bytes(ds.PixelData)
        return 0x0000

    def stop(self):
        self.server.shutdown()


class QRBase(unittest.TestCase):
    mode = "edge"

    def setUp(self):
        from vyonix.config import Config
        from vyonix.context import build
        from vyonix.pacs import service as pacs
        from vyonix.pacs.dimse_qr import QRServer
        from tests_platform.test_licensing import Base
        from tests.licensing_support import Computer
        self.tmp = Path(tempfile.mkdtemp(prefix="vyx-qr-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sfx = secrets.token_hex(3)
        self.code = f"qr-{self.sfx}"
        self.t = new_org(db, self.code)
        self.b = MemoryBackend()
        self.b.name = f"mem-{self.sfx}"
        h = Base.__new__(Base)
        h.keys = {}
        cfg = Config(data_dir=self.tmp / "data", default_organization=self.code, mode=self.mode)
        self.plat = build(cfg, licensing=h.licensing(Computer()), db=db)
        self.pacs = pacs
        self.data = {}
        with db.session(self.t) as s:
            for i in (1, 2):
                d = make_dicom(sop=uid(1, 1, i), instance_number=i, fill=i * 100, patient_id="QR-1",
                               patient_name="CONSULTA^SINTETICA", accession="ACQ")
                pacs.ingest(s, self.b, d, actor="teste")
                self.data[uid(1, 1, i)] = d
        self.port = free_port()
        self.qr = QRServer(self.plat, port=self.port, ae_title="VYONIX_QR", bind="127.0.0.1", backend=self.b)
        self.qr.start()
        self.addCleanup(self.qr.stop)

    def node(self, ae, tid=None, **kw):
        with db.session(tid or self.t) as s:
            return self.pacs.add_node(s, ae, actor="admin", **kw)

    def assoc(self, calling, called="VYONIX_QR"):
        from pynetdicom import AE
        from pynetdicom.sop_class import (StudyRootQueryRetrieveInformationModelFind,
                                          StudyRootQueryRetrieveInformationModelMove, Verification)
        ae = AE(ae_title=calling)
        for c in (Verification, StudyRootQueryRetrieveInformationModelFind, StudyRootQueryRetrieveInformationModelMove):
            ae.add_requested_context(c)
        return ae.associate("127.0.0.1", self.port, ae_title=called)

    @staticmethod
    def query(level, **kw):
        from pydicom.dataset import Dataset
        q = Dataset()
        q.QueryRetrieveLevel = level
        for k, v in kw.items():
            setattr(q, k, v)
        return q

    def audit(self, action, tid=None):
        from vyonix.audit import service as audit
        with db.session(tid or self.t) as s:
            return audit.query(s, action=action)


class QREdge(QRBase):
    def test_unknown_or_wrong_address_or_wrong_called_ae_refused(self):
        # recusa = associação não estabelecida (A-ASSOCIATE-RJ; o cliente pode ver a conexão encerrada logo depois)
        self.assertFalse(self.assoc("DESCONHECIDO").is_established)
        self.node("ESTACAO_IP", host="10.9.9.9")                 # IP cadastrado diferente do da associação
        self.assertFalse(self.assoc("ESTACAO_IP").is_established)
        self.node("SO_RECEBE", host="127.0.0.1", port=104, can_query=False, can_receive=True)
        self.assertFalse(self.assoc("SO_RECEBE").is_established)     # cadastrado, mas sem permissão de consultar
        self.node("ESTACAO")
        self.assertFalse(self.assoc("ESTACAO", called="OUTRO_AE").is_established)
        a = self.assoc("estacao")                                # AE normalizado
        self.assertTrue(a.is_established)
        self.assertEqual(a.send_c_echo().Status, 0x0000)
        a.release()

    def test_find_levels(self):
        from pynetdicom.sop_class import StudyRootQueryRetrieveInformationModelFind as FIND
        self.node("ESTACAO", host="127.0.0.1")
        a = self.assoc("ESTACAO")
        try:
            res = [(st.Status, ds) for st, ds in a.send_c_find(
                self.query("STUDY", PatientID="QR-1", StudyInstanceUID="", PatientName="", StudyDate="",
                           NumberOfStudyRelatedInstances=""), FIND)]
            hits = [ds for st, ds in res if st == 0xFF00]
            self.assertEqual(len(hits), 1)
            self.assertEqual(str(hits[0].StudyInstanceUID), uid(1))
            self.assertEqual(str(hits[0].PatientName), "CONSULTA^SINTETICA")
            self.assertEqual(int(hits[0].NumberOfStudyRelatedInstances), 2)
            self.assertEqual(hits[0].RetrieveAETitle, "VYONIX_QR")
            self.assertEqual(res[-1][0], 0x0000)
            none = [st.Status for st, _ in a.send_c_find(self.query("STUDY", PatientID="NINGUEM",
                                                                     StudyInstanceUID=""), FIND)]
            self.assertEqual(none, [0x0000])
            series = [ds for st, ds in a.send_c_find(self.query("SERIES", StudyInstanceUID=uid(1),
                                                                 SeriesInstanceUID="", Modality=""), FIND)
                      if st and st.Status == 0xFF00]
            self.assertEqual([str(d.SeriesInstanceUID) for d in series], [uid(1, 1)])
            images = [ds for st, ds in a.send_c_find(self.query("IMAGE", StudyInstanceUID=uid(1),
                                                                 SeriesInstanceUID=uid(1, 1), SOPInstanceUID=""), FIND)
                      if st and st.Status == 0xFF00]
            self.assertEqual(sorted(str(d.SOPInstanceUID) for d in images), sorted(self.data))
        finally:
            a.release()
        found = self.audit("pacs.qr.find")
        self.assertEqual(len(found), 4)
        self.assertNotIn("QR-1", str([f.details for f in found]))     # auditoria sem dados do paciente

    def test_move_to_unregistered_and_registered_destination(self):
        from pynetdicom.sop_class import StudyRootQueryRetrieveInformationModelMove as MOVE
        self.node("ESTACAO", host="127.0.0.1")
        rx = Receiver("DESTINO")
        self.addCleanup(rx.stop)
        a = self.assoc("ESTACAO")
        try:
            st = [s.Status for s, _ in a.send_c_move(self.query("STUDY", StudyInstanceUID=uid(1)), "DESTINO", MOVE)]
            self.assertEqual(st[-1], 0xA801)                         # destino não cadastrado
            self.node("DESTINO", host="127.0.0.1", port=rx.port, can_query=False, can_receive=True)
            st = [s.Status for s, _ in a.send_c_move(self.query("STUDY", StudyInstanceUID=uid(1)), "DESTINO", MOVE)]
            self.assertEqual(st[-1], 0x0000)
        finally:
            a.release()
        self.assertEqual(sorted(rx.received), sorted(self.data))
        from pydicom import dcmread
        import io
        for sop, data in self.data.items():                         # pixel idêntico ao recebido na entrada
            self.assertEqual(rx.received[sop], bytes(dcmread(io.BytesIO(data)).PixelData))
        moves = self.audit("pacs.qr.move")
        self.assertEqual(moves[0].details["sent"], 2)
        self.assertTrue(any(e.details.get("purpose") == "dimse-move" for e in self.audit("pacs.study.open")))

    def get_assoc(self, calling):
        from pynetdicom import AE, build_role, evt
        from pynetdicom.sop_class import CTImageStorage, MRImageStorage, StudyRootQueryRetrieveInformationModelGet
        got: dict[str, bytes] = {}

        def store(event):
            got[str(event.dataset.SOPInstanceUID)] = bytes(event.dataset.PixelData)
            return 0x0000
        ae = AE(ae_title=calling)
        ae.add_requested_context(StudyRootQueryRetrieveInformationModelGet)
        roles = []
        for c in (CTImageStorage, MRImageStorage):
            ae.add_requested_context(c)
            roles.append(build_role(c, scp_role=True))
        a = ae.associate("127.0.0.1", self.port, ae_title="VYONIX_QR", ext_neg=roles,
                         evt_handlers=[(evt.EVT_C_STORE, store)])
        return a, got

    def test_get_only_for_node_allowed_to_receive(self):
        from pynetdicom.sop_class import StudyRootQueryRetrieveInformationModelGet as GET
        self.node("SOCONSULTA", host="127.0.0.1")                      # pode consultar, não pode receber
        a, got = self.get_assoc("SOCONSULTA")
        try:
            st = [s.Status for s, _ in a.send_c_get(self.query("STUDY", StudyInstanceUID=uid(1)), GET) if s]
        finally:
            a.release()
        self.assertNotEqual(st[-1], 0x0000)
        self.assertEqual(got, {})
        self.node("VIEWER_GET", host="127.0.0.1", port=11112, can_receive=True)
        a, got = self.get_assoc("VIEWER_GET")
        try:
            st = [s.Status for s, _ in a.send_c_get(self.query("STUDY", StudyInstanceUID=uid(1)), GET) if s]
            self.assertEqual(st[-1], 0x0000)
            st = [s.Status for s, _ in a.send_c_get(self.query("IMAGE", StudyInstanceUID=uid(1),
                  SeriesInstanceUID=uid(1, 1), SOPInstanceUID=uid(1, 1, 2)), GET) if s]
            self.assertEqual(st[-1], 0x0000)
        finally:
            a.release()
        from pydicom import dcmread
        import io
        self.assertEqual(sorted(got), sorted(self.data))
        for sop, data in self.data.items():
            self.assertEqual(got[sop], bytes(dcmread(io.BytesIO(data)).PixelData))
        gets = self.audit("pacs.qr.get")
        self.assertEqual(sorted(e.details["sent"] for e in gets), [1, 2])
        self.assertTrue(any(e.details.get("purpose") == "dimse-get" for e in self.audit("pacs.study.open")))

    def test_corrupted_file_in_engine_is_not_sent(self):
        from pynetdicom.sop_class import StudyRootQueryRetrieveInformationModelMove as MOVE
        self.node("ESTACAO", host="127.0.0.1")
        rx = Receiver("DESTINO")
        self.addCleanup(rx.stop)
        self.node("DESTINO", host="127.0.0.1", port=rx.port, can_query=False, can_receive=True)
        bid = next(k for k, v in self.b.files.items() if v == self.data[uid(1, 1, 1)])
        self.b.files[bid] = self.b.files[bid][:-1] + bytes([self.b.files[bid][-1] ^ 0xFF])
        a = self.assoc("ESTACAO")
        try:
            list(a.send_c_move(self.query("STUDY", StudyInstanceUID=uid(1)), "DESTINO", MOVE))
        finally:
            a.release()
        self.assertEqual(sorted(rx.received), [uid(1, 1, 2)])
        self.assertEqual(self.audit("pacs.qr.move")[0].details["integrity_failures"], 1)
        from pynetdicom.sop_class import StudyRootQueryRetrieveInformationModelGet as GET
        self.node("VIEWER_GET", host="127.0.0.1", port=11112, can_receive=True)
        a, got = self.get_assoc("VIEWER_GET")                          # C-GET: mesma conferência
        try:
            list(a.send_c_get(self.query("STUDY", StudyInstanceUID=uid(1)), GET))
        finally:
            a.release()
        self.assertEqual(sorted(got), [uid(1, 1, 2)])
        self.assertEqual(self.audit("pacs.qr.get")[0].details["integrity_failures"], 1)

    def test_node_validation(self):
        from vyonix.errors import Conflict, ValidationFailed
        with self.assertRaises(ValidationFailed):
            self.node("DESTINO", can_query=False, can_receive=True)          # destino sem IP/porta
        with self.assertRaises(ValidationFailed):
            self.node("X", host="estação inválida!")                          # nem IP nem nome de máquina
        self.assertEqual(self.node("PELO_NOME", host="Estacao-TC.local")["host"], "estacao-tc.local")
        with self.assertRaises(ValidationFailed):
            self.node("X", can_query=False, can_receive=False)
        self.node("DUPLO")
        with self.assertRaises(Conflict):
            self.node("duplo")


class QRCloud(QRBase):
    mode = "cloud"

    def test_node_of_other_org_cannot_use_this_org_ae(self):
        from pynetdicom.sop_class import StudyRootQueryRetrieveInformationModelFind as FIND
        other = new_org(db, f"qr-b-{self.sfx}")
        ae_a, ae_b = f"QRA_{self.sfx.upper()}", f"QRB_{self.sfx.upper()}"
        with db.session(self.t) as s:
            self.pacs.add_route(s, ae_a, actor="admin")
        with db.session(other) as s:
            self.pacs.add_route(s, ae_b, actor="admin")
        self.node("ESTACAO_B", tid=other, host="127.0.0.1")          # estação cadastrada só na organização B
        self.assertFalse(self.assoc("ESTACAO_B", called=ae_a).is_established)   # B chamando o AE de A: recusada
        self.assertFalse(self.assoc("ESTACAO_B", called="SEM_ROTA").is_established)
        a = self.assoc("ESTACAO_B", called=ae_b)
        self.assertTrue(a.is_established)
        try:
            hits = [ds for st, ds in a.send_c_find(self.query("STUDY", StudyInstanceUID=uid(1), PatientID=""), FIND)
                    if st and st.Status == 0xFF00]
            self.assertEqual(hits, [])                                # o estudo de A não aparece para B
        finally:
            a.release()


if __name__ == "__main__":
    unittest.main()
