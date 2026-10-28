"""PACS — retenção: relatório dos estudos fora do prazo configurado, guarda obrigatória com motivo e auditoria,
nada excluído, isolamento entre organizações. PostgreSQL real, motor dublê; dados sintéticos."""

from __future__ import annotations

import unittest
from datetime import date

from tests_platform.pacs_support import MemoryBackend, make_dicom, uid
from tests_platform.support import new_org, require_db


def setUpModule():
    global db
    db = require_db()


class Retention(unittest.TestCase):
    def setUp(self):
        from vyonix.pacs import service as pacs
        self.t = new_org(db)
        self.b = MemoryBackend()
        with db.session(self.t) as s:
            for i, d in enumerate(("19990105", "20050310", "20240101"), start=1):
                pacs.ingest(s, self.b, make_dicom(study=uid(90 + i), series=uid(90 + i, 1), sop=uid(90 + i, 1, 1),
                                                  study_date=d, patient_id=f"RT{i}"), actor="t")

    def test_report_hold_and_nothing_deleted(self):
        from sqlalchemy import func, select
        from vyonix.audit import service as audit
        from vyonix.errors import NotFound, ValidationFailed
        from vyonix.pacs import retention
        from vyonix.pacs.models import PacsInstance
        from vyonix.settings import service as settings
        today = date(2026, 10, 28)
        with db.session(self.t) as s:
            r = retention.report(s, today=today)
            self.assertEqual((r["years"], r["cutoff"], r["eligible"]), (20, "2006-10-28", 2))
            self.assertEqual([x["study_uid"] for x in r["items"]], [uid(91), uid(92)])     # mais antigo primeiro
            self.assertGreater(r["eligible_bytes"], 0)
            with self.assertRaises(ValidationFailed):
                retention.set_hold(s, uid(91), True, reason=" ", actor="adm")
            with self.assertRaises(NotFound):
                retention.set_hold(s, "1.2.3", True, reason="x", actor="adm")
            retention.set_hold(s, uid(91), True, reason="Processo judicial (sintético)", actor="adm")
            r = retention.report(s, today=today)
            self.assertEqual((r["eligible"], r["eligible_on_hold"], r["on_hold"]), (1, 1, 1))
            settings.put(s, "pacs", "retention", {"years": 25}, actor="adm", reason="teste")
            self.assertEqual(retention.report(s, today=today)["eligible"], 0)
            with self.assertRaises(ValidationFailed):
                settings.put(s, "pacs", "retention", {"years": 2}, actor="adm", reason="teste")
            self.assertEqual(s.execute(select(func.count()).select_from(PacsInstance)).scalar(), 3)
            self.assertEqual(len(audit.query(s, action="pacs.retention.hold")), 1)
        self.assertEqual(len(self.b.files), 3)                                           # motor intacto
        other = new_org(db)
        with db.session(other) as s:
            self.assertEqual(retention.report(s, today=today)["eligible"], 0)
            with self.assertRaises(NotFound):
                retention.set_hold(s, uid(92), True, reason="x", actor="adm")


if __name__ == "__main__":
    unittest.main()
