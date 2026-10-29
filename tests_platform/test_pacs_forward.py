"""Encaminhamento de estudos (roteamento): regra por modalidade e origem, espera do fim da recepção, C-STORE real para
um Storage SCP (pynetdicom), conteúdo idêntico, integridade violada não enviada, novas tentativas com destino fora do
ar, envio manual, validações e isolamento entre organizações. PostgreSQL real; motor DUBLÊ DE TESTE; dados
sintéticos."""

from __future__ import annotations

import unittest
from datetime import timedelta

from tests_platform.pacs_support import MemoryBackend, make_dicom, uid
from tests_platform.support import new_org, require_db
from tests_platform.test_pacs_qr import Receiver, free_port


def setUpModule():
    global db
    db = require_db()


class Forward(unittest.TestCase):
    def setUp(self):
        from vyonix.context import build_bus
        self.t = new_org(db)
        self.b = MemoryBackend()
        self.bus = build_bus()
        self.rx = Receiver("DESTINO_PACS")
        self.addCleanup(self.rx.stop)
        from vyonix.pacs import nodes
        with db.session(self.t) as s:
            self.dest = nodes.add(s, "DESTINO_PACS", host="127.0.0.1", port=self.rx.port, can_query=False,
                                  can_receive=True, actor="admin")
            self.down = nodes.add(s, "FORA_DO_AR", host="127.0.0.1", port=free_port(), can_query=False,
                                  can_receive=True, actor="admin")
            self.only_query = nodes.add(s, "SO_CONSULTA", can_query=True, actor="admin")

    def ingest(self, n, modality="CT", station="TC_SALA1", images=2):
        from vyonix.events.worker import process_batch
        from vyonix.pacs import service as pacs
        with db.session(self.t) as s:
            for i in range(1, images + 1):
                pacs.ingest(s, self.b, make_dicom(study=uid(n), series=uid(n, 1), sop=uid(n, 1, i), modality=modality,
                                                  instance_number=i, fill=i, station=station, patient_id=f"F{n}"),
                            actor="pacs-sync", via="dimse")
        while process_batch(db, self.bus):
            pass

    def run_due(self, minutes=3):
        from vyonix.db.base import utcnow
        from vyonix.pacs import forward
        with db.session(self.t) as s:
            return forward.process_due(s, self.b, calling_ae="VYONIX_QR", now=utcnow() + timedelta(minutes=minutes))

    def rule(self, **kw):
        from vyonix.pacs import forward
        with db.session(self.t) as s:
            return forward.save_rule(s, actor="admin", **kw)

    def test_rule_by_modality_waits_stable_and_sends_identical_images(self):
        from vyonix.pacs import forward, nodes
        self.rule(name="TC para o PACS externo", destination_node_id=self.dest["id"], modality="ct")
        self.ingest(1, modality="CT")
        self.ingest(2, modality="MR")                                    # não combina
        out = self.run_due(minutes=0)                                    # recepção ainda "aberta": espera
        self.assertEqual((out["done"], out["waiting"]), (0, 0))         # vence só depois do tempo de estabilização
        out = self.run_due(minutes=3)
        self.assertEqual(out["done"], 1)
        self.assertEqual(sorted(self.rx.received), [uid(1, 1, 1), uid(1, 1, 2)])
        import pydicom
        import io
        for sop, data in ((uid(1, 1, 1), make_dicom(study=uid(1), series=uid(1, 1), sop=uid(1, 1, 1), modality="CT",
                                                    instance_number=1, fill=1, station="TC_SALA1", patient_id="F1")),):
            self.assertEqual(self.rx.received[sop], bytes(pydicom.dcmread(io.BytesIO(data)).PixelData))
        with db.session(self.t) as s:
            j = forward.jobs(s)
            self.assertEqual([(x["status"], x["sent"], x["destination"]) for x in j], [("done", 2, "DESTINO_PACS")])
            ev = nodes.events(s, node_id=self.dest["id"])
            self.assertEqual((ev[0]["direction"], ev[0]["service"], ev[0]["outcome"], ev[0]["count"]),
                             ("out", "store", "ok", 2))
            from vyonix.audit import service as audit
            self.assertEqual(audit.query(s, action="pacs.forward.attempt")[0].details["status"], "done")
        self.assertEqual(self.run_due(minutes=10)["done"], 0)           # não reenvia

    def test_source_filter_retry_backoff_then_failed(self):
        from vyonix.pacs import forward
        from vyonix.pacs.models import PacsForwardJob
        self.rule(name="Sala 2 para fora do ar", destination_node_id=self.down["id"], source="tc_sala2")
        self.ingest(3, station="TC_SALA1")                               # outra origem: não combina
        self.ingest(4, station="TC_SALA2")
        out = self.run_due()
        self.assertEqual(out["retry"], 1)
        with db.session(self.t) as s:
            j = s.query(PacsForwardJob).one()
            self.assertEqual((j.attempts, j.status), (1, "queued"))
            self.assertIn("não aceitou", j.last_error)
            first_next = j.next_attempt_at
        self.assertEqual(self.run_due(minutes=4)["retry"], 0)            # ainda não venceu (5 min)
        self.assertGreater(first_next, __import__("vyonix.db.base", fromlist=["utcnow"]).utcnow())
        for m in (10, 30, 120, 400, 1500):
            self.run_due(minutes=m)
        with db.session(self.t) as s:
            j = s.query(PacsForwardJob).one()
            self.assertEqual((j.status, j.attempts), ("failed", 6))
            r = forward.retry(s, j.id, actor="admin")
            self.assertEqual((r["status"], r["attempts"]), ("queued", 0))

    def test_integrity_violation_not_sent_and_manual_request(self):
        from vyonix.errors import ValidationFailed
        from vyonix.pacs import forward
        self.ingest(5)
        bid = next(k for k, v in self.b.files.items() if uid(5, 1, 2).encode() in v)
        self.b.files[bid] = self.b.files[bid][:-4] + b"XXXX"             # corrompido no motor
        with db.session(self.t) as s:
            with self.assertRaises(ValidationFailed):                    # destino sem "recebe estudos"
                forward.request(s, uid(5), self.only_query["id"], actor="admin")
            forward.request(s, uid(5), self.dest["id"], actor="admin")
        self.run_due()
        self.assertEqual(sorted(self.rx.received), [uid(5, 1, 1)])
        with db.session(self.t) as s:
            j = forward.jobs(s)[0]
            self.assertEqual((j["status"], j["sent"], j["integrity_failures"]), ("done", 1, 1))
            self.assertIn("integridade", j["last_error"])

    def test_isolation_rule_cannot_target_other_org_node(self):
        from vyonix.errors import ValidationFailed
        from vyonix.pacs import forward
        other = new_org(db)
        with db.session(other) as s:
            with self.assertRaises(ValidationFailed):
                forward.save_rule(s, name="x", destination_node_id=self.dest["id"], actor="intruso")
            self.assertEqual(forward.rules(s), [])


if __name__ == "__main__":
    unittest.main()
