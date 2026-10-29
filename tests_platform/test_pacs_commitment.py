"""Storage Commitment Push Model pelo Q/R do Core, com associações DICOM reais (pynetdicom dos dois lados): só
equipamento com "envia imagens"; confirmação só de instância indexada, da mesma classe e com SHA-256 conferido no
arquivo relido do motor; resultado por N-EVENT-REPORT numa associação nova; C-FIND recusado ao nó só de envio;
histórico e auditoria. PostgreSQL real; motor DUBLÊ DE TESTE; dados sintéticos."""

from __future__ import annotations

import secrets
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

from tests_platform.pacs_support import CT, MemoryBackend, make_dicom, uid
from tests_platform.support import new_org, require_db
from tests_platform.test_pacs_qr import free_port

PUSH = "1.2.840.10008.1.20.1"
PUSH_I = "1.2.840.10008.1.20.1.1"


def setUpModule():
    global db
    db = require_db()


class Modality:
    """Equipamento: recebe o N-EVENT-REPORT (papel SCU do Storage Commitment) e pede o commitment."""

    def __init__(self, ae_title: str) -> None:
        from pynetdicom import AE, evt
        self.ae_title, self.port = ae_title, free_port()
        self.reports: list = []
        self.got = threading.Event()
        ae = AE(ae_title=ae_title)
        ae.add_supported_context(PUSH, scu_role=True, scp_role=True)
        self.server = ae.start_server(("127.0.0.1", self.port), block=False,
                                      evt_handlers=[(evt.EVT_N_EVENT_REPORT, self._report)])

    def _report(self, event):
        self.reports.append((event.event_type, event.event_information))
        self.got.set()
        return 0x0000, None

    def request(self, qr_port: int, refs, tx: str):
        from pydicom.dataset import Dataset
        from pynetdicom import AE
        ae = AE(ae_title=self.ae_title)
        ae.add_requested_context(PUSH)
        a = ae.associate("127.0.0.1", qr_port, ae_title="VYONIX_QR")
        if not a.is_established:
            return None
        ds = Dataset()
        ds.TransactionUID = tx
        ds.ReferencedSOPSequence = []
        for cls, sop in refs:
            it = Dataset()
            it.ReferencedSOPClassUID, it.ReferencedSOPInstanceUID = cls, sop
            ds.ReferencedSOPSequence.append(it)
        st, _ = a.send_n_action(ds, 1, PUSH, PUSH_I)
        a.release()
        return st.Status

    def stop(self):
        self.server.shutdown()


class Commitment(unittest.TestCase):
    def setUp(self):
        from tests.licensing_support import Computer
        from tests_platform.test_licensing import Base
        from vyonix.config import Config
        from vyonix.context import build
        from vyonix.pacs import service as pacs
        from vyonix.pacs.dimse_qr import QRServer
        self.tmp = Path(tempfile.mkdtemp(prefix="vyx-commit-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        code = f"commit-{secrets.token_hex(3)}"
        self.t = new_org(db, code)
        self.b = MemoryBackend()
        h = Base.__new__(Base)
        h.keys = {}
        plat = build(Config(data_dir=self.tmp / "data", default_organization=code, mode="edge"),
                     licensing=h.licensing(Computer()), db=db)
        with db.session(self.t) as s:
            for i in (1, 2, 3):
                pacs.ingest(s, self.b, make_dicom(sop=uid(1, 1, i), instance_number=i, fill=i), actor="teste")
        self.port = free_port()
        self.qr = QRServer(plat, port=self.port, ae_title="VYONIX_QR", bind="127.0.0.1", backend=self.b)
        self.qr.start()
        self.addCleanup(self.qr.stop)
        self.mod = Modality("TC_COMMIT")
        self.addCleanup(self.mod.stop)

    def test_commitment_confirms_only_verified_instances(self):
        from pynetdicom import AE
        from pynetdicom.sop_class import StudyRootQueryRetrieveInformationModelFind as FIND
        from vyonix.audit import service as audit
        from vyonix.pacs import nodes
        with db.session(self.t) as s:
            nodes.add(s, "TC_COMMIT", host="127.0.0.1", port=self.mod.port, can_store=True, can_query=False,
                      actor="admin")
            nodes.add(s, "SO_CONSULTA", can_query=True, actor="admin")
        bid = next(k for k, v in self.b.files.items() if uid(1, 1, 3).encode() in v)
        self.b.files[bid] = self.b.files[bid][:-4] + b"XXXX"              # corrompido no motor
        refs = [(CT, uid(1, 1, 1)), (CT, uid(1, 1, 2)), (CT, uid(1, 1, 3)), (CT, uid(1, 1, 99)),
                ("1.2.840.10008.5.1.4.1.1.4", uid(1, 1, 1))]
        self.assertEqual(self.mod.request(self.port, refs, uid(5000)), 0x0000)
        self.assertTrue(self.mod.got.wait(15), "N-EVENT-REPORT não chegou")
        etype, info = self.mod.reports[0]
        self.assertEqual(etype, 2)                                         # há falhas
        self.assertEqual(str(info.TransactionUID), uid(5000))
        self.assertEqual(sorted(str(x.ReferencedSOPInstanceUID) for x in info.ReferencedSOPSequence),
                         [uid(1, 1, 1), uid(1, 1, 2)])
        fails = {(str(x.ReferencedSOPInstanceUID), str(x.ReferencedSOPClassUID)): int(x.FailureReason)
                 for x in info.FailedSOPSequence}
        self.assertEqual(fails, {(uid(1, 1, 3), CT): 0x0110, (uid(1, 1, 99), CT): 0x0112,
                                 (uid(1, 1, 1), "1.2.840.10008.5.1.4.1.1.4"): 0x0119})
        # nó só de envio não consulta
        ae = AE(ae_title="TC_COMMIT")
        ae.add_requested_context(FIND)
        a = ae.associate("127.0.0.1", self.port, ae_title="VYONIX_QR")
        self.assertTrue(a.is_established)
        from pydicom.dataset import Dataset
        q = Dataset()
        q.QueryRetrieveLevel, q.StudyInstanceUID = "STUDY", ""
        statuses = [st.Status for st, _ in a.send_c_find(q, FIND) if st]
        a.release()
        self.assertNotIn(0xFF00, statuses)
        for _ in range(50):
            with db.session(self.t) as s:
                done = audit.query(s, action="pacs.commitment")
            if done:
                break
            time.sleep(0.1)
        self.assertEqual((done[0].details["committed"], done[0].details["failed"]), (2, 3))
        with db.session(self.t) as s:
            ev = nodes.events(s)
        self.assertTrue(any(e["service"] == "commit" and e["outcome"] == "ok" for e in ev), ev)
        # nó só de consulta não pede commitment
        q_only = Modality("SO_CONSULTA")
        self.addCleanup(q_only.stop)
        self.assertEqual(q_only.request(self.port, refs[:1], uid(5001)), 0x0124)


if __name__ == "__main__":
    unittest.main()
