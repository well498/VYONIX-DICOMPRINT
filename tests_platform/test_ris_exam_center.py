"""Central de exames (RIS): etapa de cada pedido (pedido, agendado, em realização, imagens, laudo em redação,
liberado, cancelado), atrasos (sem agendamento urgente, aquisição, laudo fora do prazo, imagens incompletas), tempos e
isolamento entre organizações. PostgreSQL real; dados sintéticos."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from tests_platform.pacs_support import MemoryBackend, make_dicom
from tests_platform.support import new_org, require_db

BRT = timezone(timedelta(hours=-3))
DAY = date(2026, 11, 10)


def setUpModule():
    global db
    db = require_db()
    from tests_platform import test_report, test_ris
    test_report.db = test_ris.db = db


class ExamCenter(unittest.TestCase):
    def setUp(self):
        from tests_platform.test_report import make_physician
        from tests_platform.test_ris import make_order
        from vyonix.clinical import service as clinical
        from vyonix.pacs import service as pacs
        from vyonix.report import service as rep
        from vyonix.ris import service as ris
        self.t = new_org(db)
        uid, _ = make_physician(self.t)
        b = MemoryBackend()
        at = lambda h: datetime(2026, 11, 10, h, 0, tzinfo=BRT)   # noqa: E731
        self.o = {k: make_order(self.t, name=f"Paciente {k} Sintetico")[0]
                  for k in ("requested", "scheduled", "images", "reporting", "reported", "cancelled")}
        with db.session(self.t) as s:
            from vyonix.clinical.models import Order
            s.get(Order, self.o["requested"]).priority = "urgent"
            sch = {}
            for k in ("scheduled", "images", "reporting", "reported", "cancelled"):
                sch[k] = ris.schedule(s, self.o[k], scheduled_at=at(8 + len(sch)), modality="CT", actor="recep")
            clinical.set_order_status(s, self.o["cancelled"], "cancelled", actor="recep")
            for i, k in enumerate(("images", "reporting", "reported"), start=1):
                st_uid = sch[k].study_instance_uid
                pacs.ingest(s, b, make_dicom(study=st_uid, series=st_uid + ".1", sop=st_uid + ".1.1",
                                             patient_id=f"EC{i}", accession=""), actor="t")
                st = clinical.register_study(s, study_instance_uid=st_uid, modality="CT", study_date=DAY, actor="t")
                clinical.reconcile(s, st.id, self.o[k], actor="t")
                if k != "images":
                    r = rep.open_report(s, st.id, actor="med", actor_id=uid)
                    rep.update_draft(s, r.id, body="Achados: sintético.", actor="med")
                    if k == "reported":
                        rep.finalize(s, r.id, actor="med", actor_id=uid)

    def center(self, **kw):
        from vyonix.ris import tracking
        with db.session(self.t) as s:
            return tracking.exam_center(s, date_from=date(2026, 10, 1), date_to=date(2026, 12, 31), **kw)

    def test_stages_flags_and_times(self):
        res = self.center(now=datetime(2026, 11, 10, 6, 0, tzinfo=BRT) + timedelta(days=1))
        stage = {x["order_id"]: x["stage"] for x in res["items"]}
        self.assertEqual({k: stage[str(v)] for k, v in self.o.items()},
                         {k: k for k in self.o})
        by = {x["order_id"]: x for x in res["items"]}
        self.assertIn("not_scheduled", by[str(self.o["requested"])]["flags"])        # urgente sem agendamento
        self.assertIn("late_acquisition", by[str(self.o["scheduled"])]["flags"])
        self.assertEqual(by[str(self.o["reported"])]["flags"], [])
        self.assertEqual(by[str(self.o["images"])]["images"], 1)
        self.assertIsNotNone(by[str(self.o["reported"])]["minutes_to_report"])
        self.assertEqual(res["by_stage"]["reported"], 1)
        self.assertEqual(res["total"], 6)
        later = self.center(now=datetime(2026, 11, 20, tzinfo=BRT))                  # rotina: 48 h para laudar
        flags = {x["order_id"]: x["flags"] for x in later["items"]}
        self.assertIn("late_report", flags[str(self.o["images"])])
        self.assertIn("late_report", flags[str(self.o["reporting"])])
        only = self.center(now=datetime(2026, 11, 20, tzinfo=BRT), late_only=True)
        self.assertNotIn(str(self.o["reported"]), {x["order_id"] for x in only["items"]})
        self.assertEqual(only["by_stage"], later["by_stage"])                        # filtro não muda os totais
        st = self.center(stage="reporting")
        self.assertEqual([x["order_id"] for x in st["items"]], [str(self.o["reporting"])])
        self.assertEqual(self.center(modality="MR")["items"], [])

    def test_other_org_sees_nothing_and_api(self):
        from vyonix.ris import tracking
        other = new_org(db)
        with db.session(other) as s:
            res = tracking.exam_center(s, date_from=date(2026, 10, 1), date_to=date(2026, 12, 31))
        self.assertEqual((res["items"], res["total"]), ([], 0))


if __name__ == "__main__":
    unittest.main()
