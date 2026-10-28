"""Backup e restauração do PACS: exportação verificada e incremental, verificação do backup, falha de integridade no
motor, recusa de backup adulterado ou de outra organização, e recuperação de desastre (motor vazio com o índice
intacto; motor e índice vazios). PostgreSQL real; motor DUBLÊ DE TESTE ``MemoryBackend``; dados sintéticos."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from tests_platform.pacs_support import MemoryBackend, make_dicom, uid
from tests_platform.support import new_org, require_db


def setUpModule():
    global db
    db = require_db()


class Backup(unittest.TestCase):
    def setUp(self):
        from vyonix.pacs import backup, service as pacs
        self.backup, self.pacs = backup, pacs
        self.tmp = Path(tempfile.mkdtemp(prefix="vyx-pacs-bkp-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.t = new_org(db)
        self.b = MemoryBackend()
        self.data = {}
        with db.session(self.t) as s:
            for st, n in ((1, 2), (2, 1)):
                for i in range(1, n + 1):
                    d = make_dicom(study=uid(st), series=uid(st, 1), sop=uid(st, 1, i), instance_number=i,
                                   patient_id=f"BK-{st}", fill=st * 10 + i)
                    pacs.ingest(s, self.b, d, actor="teste")
                    self.data[uid(st, 1, i)] = d
        self.dest = self.tmp / "backup"

    def test_export_incremental_and_verify(self):
        from vyonix.audit import service as audit
        out = self.backup.export(db, self.t, self.b, self.dest)
        self.assertEqual((out["instances"], out["copied"], out["already_present"], out["integrity_failures"]),
                         (3, 3, 0, []))
        f = self.dest / uid(1) / uid(1, 1) / f"{uid(1, 1, 2)}.dcm"
        self.assertEqual(f.read_bytes(), self.data[uid(1, 1, 2)])
        again = self.backup.export(db, self.t, self.b, self.dest)
        self.assertEqual((again["copied"], again["already_present"]), (0, 3))       # incremental
        v = self.backup.verify(self.dest)
        self.assertTrue(v["valid"])
        self.assertEqual((v["instances"], v["ok"], v["extra"]), (3, 3, []))
        with db.session(self.t) as s:
            self.assertEqual(len(audit.query(s, action="pacs.backup.export")), 2)

    def test_integrity_failure_in_engine_is_not_copied(self):
        bid = next(k for k, v in self.b.files.items() if v == self.data[uid(2, 1, 1)])
        self.b.files[bid] = self.b.files[bid][:-1] + bytes([self.b.files[bid][-1] ^ 0xFF])
        out = self.backup.export(db, self.t, self.b, self.dest)
        self.assertEqual(out["instances"], 2)
        self.assertEqual([f["sop_uid"] for f in out["integrity_failures"]], [uid(2, 1, 1)])
        self.assertFalse((self.dest / uid(2) / uid(2, 1) / f"{uid(2, 1, 1)}.dcm").exists())

    def test_tampered_or_incomplete_backup_is_refused(self):
        self.backup.export(db, self.t, self.b, self.dest)
        f = self.dest / uid(1) / uid(1, 1) / f"{uid(1, 1, 1)}.dcm"
        raw = f.read_bytes()
        f.write_bytes(raw[:-1] + bytes([raw[-1] ^ 0xFF]))
        (self.dest / uid(2) / uid(2, 1) / f"{uid(2, 1, 1)}.dcm").unlink()
        v = self.backup.verify(self.dest)
        self.assertFalse(v["valid"])
        self.assertEqual(len(v["altered"]), 1)
        self.assertEqual(len(v["missing"]), 1)
        with self.assertRaises(ValueError):
            self.backup.restore(db, self.t, MemoryBackend(), self.dest)

    def test_restore_refuses_other_organization(self):
        self.backup.export(db, self.t, self.b, self.dest)
        other = new_org(db)
        with self.assertRaises(PermissionError):
            self.backup.restore(db, other, MemoryBackend(), self.dest)

    def test_disaster_engine_lost_index_intact(self):
        """O armazenamento do motor foi perdido; o índice (PostgreSQL) sobreviveu: a restauração devolve os arquivos
        ao motor e religa o índice — sem isso o estudo apareceria na pesquisa e não abriria."""
        self.backup.export(db, self.t, self.b, self.dest)
        new_engine = MemoryBackend()                                      # motor reinstalado, vazio
        out = self.backup.restore(db, self.t, new_engine, self.dest)
        self.assertEqual((out["reinstated"], out["indexed"], out["duplicates"], out["rejected"]), (3, 0, 0, []))
        with db.session(self.t) as s:
            for sop, data in self.data.items():
                st = uid(1) if sop.startswith(uid(1) + ".") else uid(2)
                self.assertEqual(self.pacs.retrieve_instance(s, new_engine, st, st + ".1", sop), data)
        again = self.backup.restore(db, self.t, new_engine, self.dest)
        self.assertEqual((again["reinstated"], again["duplicates"]), (0, 3))      # idempotente

    def test_disaster_engine_and_index_lost(self):
        """Motor e índice perdidos (organização nova recriada): restauração explícita para outra organização."""
        from vyonix.audit import service as audit
        self.backup.export(db, self.t, self.b, self.dest)
        rebuilt = new_org(db)
        engine = MemoryBackend()
        out = self.backup.restore(db, rebuilt, engine, self.dest, allow_other_organization=True)
        self.assertEqual((out["indexed"], out["rejected"]), (3, []))
        with db.session(rebuilt) as s:
            self.assertEqual(len(self.pacs.search_studies(s, {})), 2)
            self.assertEqual(len(audit.query(s, action="pacs.backup.restore")), 1)


if __name__ == "__main__":
    unittest.main()
