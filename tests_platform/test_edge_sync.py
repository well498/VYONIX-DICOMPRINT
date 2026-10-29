"""Protótipo da sincronização edge → central (ADR-0014) com CENTRAL SIMULADO (outra organização no mesmo PostgreSQL,
motor dublê separado; nenhuma rede externa): envio e confirmação por SHA-256, queda da internet com espera crescente
e retomada, reinício do serviço (estado novo) sem perder a fila, duplicidade, conflito, arquivo corrompido no edge,
isolamento entre organizações e estatísticas de monitoramento. Dados sintéticos."""

from __future__ import annotations

import unittest
from datetime import timedelta

from tests_platform.pacs_support import MemoryBackend, make_dicom, uid
from tests_platform.support import new_org, require_db


def setUpModule():
    global db
    db = require_db()


class EdgeSync(unittest.TestCase):
    def setUp(self):
        from vyonix.pacs.edge_sync import SimulatedCentral, SyncState
        self.edge, self.central_org = new_org(db), new_org(db)
        self.b_edge, self.b_central = MemoryBackend(), MemoryBackend()
        self.central = SimulatedCentral(db, self.central_org, self.b_central)
        self.state = SyncState()

    def receive(self, n, i=1, **kw):
        from vyonix.pacs import service as pacs
        with db.session(self.edge) as s:
            pacs.ingest(s, self.b_edge, make_dicom(study=uid(n), series=uid(n, 1), sop=uid(n, 1, i), instance_number=i,
                                                   patient_id=f"E{n}", **kw), actor="pacs-sync", via="dimse")

    def round(self, minutes=0):
        from vyonix.db.base import utcnow
        from vyonix.pacs import edge_sync
        with db.session(self.edge) as s:
            return edge_sync.sync_once(s, self.b_edge, self.central, self.state, now=utcnow() + timedelta(minutes=minutes))

    def stats(self):
        from vyonix.pacs import edge_sync
        with db.session(self.edge) as s:
            return edge_sync.stats(s, self.state)

    def central_studies(self, tenant=None):
        from vyonix.pacs import service as pacs
        with db.session(tenant or self.central_org) as s:
            return sorted(x["0020000D"]["Value"][0] for x in pacs.search_studies(s, {}))

    def test_sync_offline_retry_resume_and_restart(self):
        from vyonix.pacs.edge_sync import SyncState
        for i in (1, 2, 3):
            self.receive(1, i)
        self.central.down = True                                        # internet fora
        out = self.round()
        self.assertEqual((out["enqueued"], out["retry"], out["synced"]), (3, 3, 0))
        self.assertIsNotNone(self.stats()["offline_since"])
        self.assertEqual(self.round()["retry"], 0)                      # espera de 1 min ainda não venceu
        self.receive(2)                                                 # o edge segue recebendo sem internet
        self.central.down = False
        self.state = SyncState()                                        # serviço reiniciado: a fila está no banco
        out = self.round(minutes=2)
        self.assertEqual((out["enqueued"], out["synced"]), (1, 4))
        st = self.stats()
        self.assertEqual((st["synced"], st["queued"], st["not_enqueued"], st["offline_since"]), (4, 0, 0, None))
        self.assertEqual(self.central_studies(), [uid(1), uid(2)])
        self.assertEqual(self.round(minutes=5), {"enqueued": 0, "synced": 0, "conflict": 0, "integrity": 0,
                                                 "retry": 0})          # nada é reenviado
        # arquivos idênticos no central
        self.assertEqual(sorted(self.b_central.files.values()), sorted(self.b_edge.files.values()))

    def test_duplicate_conflict_and_local_corruption(self):
        from vyonix.pacs import service as pacs
        self.receive(3)
        self.receive(4)
        self.receive(5)
        with db.session(self.central_org) as s:                       # o central já tem a 3 (idêntica)
            pacs.ingest(s, self.b_central, make_dicom(study=uid(3), series=uid(3, 1), sop=uid(3, 1, 1), patient_id="E3"),
                        actor="teste")
            # e outro conteúdo com o UID da 4
            pacs.ingest(s, self.b_central, make_dicom(study=uid(4), series=uid(4, 1), sop=uid(4, 1, 1), patient_id="E4",
                                                      fill=9), actor="teste")
        bid = next(k for k, v in self.b_edge.files.items() if uid(5, 1, 1).encode() in v)
        self.b_edge.files[bid] = self.b_edge.files[bid][:-4] + b"XXXX"  # corrompido no edge
        out = self.round()
        self.assertEqual((out["synced"], out["conflict"], out["integrity"]), (1, 1, 1))
        st = self.stats()
        self.assertEqual((st["synced"], st["conflict"], st["integrity"]), (1, 1, 1))
        self.assertNotIn(uid(5), self.central_studies())                # corrompido não saiu do edge

    def test_isolation_edge_never_reaches_other_org(self):
        other = new_org(db)
        self.receive(6)
        self.round()
        self.assertEqual(self.central_studies(), [uid(6)])
        self.assertEqual(self.central_studies(other), [])
        from vyonix.pacs.models import PacsEdgeSync
        with db.session(other) as s:                                    # a fila do edge não aparece para outra org
            self.assertEqual(s.query(PacsEdgeSync).count(), 0)


if __name__ == "__main__":
    unittest.main()
