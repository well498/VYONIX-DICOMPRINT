"""Verificação contínua da integridade do armazenamento do PACS (VyonixWorker): lotes com cursor, volta completa,
arquivo corrompido ou ausente registrado (auditoria, estado, monitoramento) sem alterar nada, e limpeza depois da
recuperação. Plataforma real, PostgreSQL real; motor DUBLÊ DE TESTE ``MemoryBackend``; dados sintéticos."""

from __future__ import annotations

import unittest

from tests_platform.pacs_support import make_dicom, uid
from tests_platform.support import require_db
from tests_platform.test_pacs import ApiBase


def setUpModule():
    global db
    db = require_db()
    from tests_platform import test_pacs
    test_pacs.db = db


class Integrity(ApiBase):
    def setUp(self):
        super().setUp()
        from vyonix.pacs.integrity_task import PacsIntegrityTask
        self.c = self.login()
        self.license_and_enable()
        self.data = {}
        for i in range(1, 6):
            d = make_dicom(study=uid(5), series=uid(5, 1), sop=uid(5, 1, i), instance_number=i, fill=i)
            body, ctype = self.stow_body(d)
            r = self.c.post("/api/v1/pacs/dicomweb/studies", content=body, headers={"Content-Type": ctype})
            self.assertEqual(r.status_code, 200, r.text)
            self.data[uid(5, 1, i)] = d
        self.task = PacsIntegrityTask(self.plat, batch=2)

    def bid(self, sop):
        return next(k for k, v in self.b.files.items() if v == self.data[sop])

    def test_batches_round_and_corruption_reported_without_changes(self):
        from vyonix.audit import service as audit
        from vyonix.pacs.integrity_task import read_state
        self.assertEqual(self.task(), {"checked": 2, "failures": 0, "round_complete": False})
        self.assertEqual(self.task()["checked"], 2)
        r = self.task()
        self.assertEqual((r["checked"], r["round_complete"]), (1, True))
        self.assertEqual(read_state(self.plat)["rounds"], 1)
        h = self.c.get("/api/v1/health/detail").json()
        self.assertEqual(h["components"]["pacs_integrity"]["failures"], 0)
        # corrompe uma e remove outra do motor (dublê)
        b3, b5 = self.bid(uid(5, 1, 3)), self.bid(uid(5, 1, 5))
        original3 = self.b.files[b3]
        self.b.files[b3] = original3[:-1] + bytes([original3[-1] ^ 0xFF])
        del self.b.files[b5]
        total = sum(self.task()["failures"] for _ in range(3))
        self.assertEqual(total, 2)
        st = read_state(self.plat)
        self.assertEqual({f["sop_uid"]: f["reason"] for f in st["failures"]},
                         {uid(5, 1, 3): "conteúdo diferente do registrado na entrada",
                          uid(5, 1, 5): "arquivo ausente no motor"})
        self.assertNotEqual(self.b.files[b3], original3)                     # nada foi "consertado" às escondidas
        with db.session(self.t) as s:
            self.assertEqual(len(audit.query(s, action="pacs.integrity.failure")), 2)
        h = self.c.get("/api/v1/health/detail").json()
        self.assertEqual(h["status"], "falha")
        self.assertTrue(any("integridade violada" in p for p in h["problems"]))
        self.assertNotIn("TESTE^SINTETICO", str(h))
        # recuperação (equivalente ao pacs-restore): a próxima volta limpa as pendências
        self.b.files[b3] = original3
        self.b.files[b5] = self.data[uid(5, 1, 5)]
        for _ in range(3):
            self.task()
        self.assertEqual(read_state(self.plat)["failures"], [])
        self.assertEqual(self.c.get("/api/v1/health/detail").json()["components"]["pacs_integrity"]["failures"], 0)

    def test_engine_down_keeps_cursor(self):
        from vyonix.pacs.integrity_task import read_state
        self.task()
        cursor = read_state(self.plat)["cursor"]
        self.b.down = True
        r = self.task()
        self.assertEqual(r["checked"], 0)
        self.assertEqual(read_state(self.plat)["cursor"], cursor)
        self.b.down = False
        self.assertEqual(self.task()["checked"], 2)


if __name__ == "__main__":
    unittest.main()
