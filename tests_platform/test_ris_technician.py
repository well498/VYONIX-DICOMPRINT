"""Painel do Técnico em Radiologia: exames do dia, estudos recebidos, recusas na recepção DICOM e pendências;
o técnico registra chegada, início e conclusão, mas não agenda, não cancela e não libera laudos.
API real (edge), PostgreSQL real, motor dublê; dados sintéticos."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from tests_platform.pacs_support import MemoryBackend, make_dicom
from tests_platform.support import require_db
from tests_platform.test_pacs import ApiBase

BRT = timezone(timedelta(hours=-3))


def setUpModule():
    global db
    db = require_db()
    from tests_platform import test_pacs, test_ris
    test_pacs.db = test_ris.db = db


class Technician(ApiBase):
    def setUp(self):
        super().setUp()
        from tests_platform.test_ris import Api
        self.base = self
        Api.license_ris(self)

    def user(self, role):
        c = self.login()
        r = c.post("/api/v1/users", json={"username": role, "display_name": role, "password": "Senha-Teste-1234",
                                          "roles": [{"role": role}]})
        self.assertEqual(r.status_code, 201, r.text)
        u = self.login(role, "Senha-Teste-1234")
        u.post("/api/v1/auth/password", json={"current": "Senha-Teste-1234", "new": "Senha-Nova-9876!"})
        return self.login(role, "Senha-Nova-9876!")

    def test_panel_and_limited_actions(self):
        from tests_platform.test_ris import make_order
        from vyonix.pacs import service as pacs
        from vyonix.ris import service as ris
        today = datetime.now(BRT).date()
        oid, _, _ = make_order(self.t)
        with db.session(self.t) as s:
            sch = ris.schedule(s, oid, scheduled_at=datetime.combine(today, datetime.min.time(), tzinfo=BRT)
                               + timedelta(hours=23), modality="CT", room="Sala Sintética", actor="recep")
            sid, uid = sch.id, sch.study_instance_uid
            b = MemoryBackend()
            pacs.ingest(s, b, make_dicom(study=uid, series=uid + ".1", sop=uid + ".1.1", patient_id="TEC1",
                                         accession=""), actor="dicom:CT_SALA1")
            with self.assertRaises(Exception):
                pacs.ingest(s, b, b"lixo que nao e dicom", actor="dicom:CT_SALA1", via="dimse")
        tec, recep = self.user("tecnico"), self.user("recepcionista")
        p = tec.get("/api/v1/ris/technician-panel", params={"day": today.isoformat()}).json()
        self.assertEqual([e["schedule_id"] for e in p["exams"]], [str(sid)])
        self.assertEqual(p["exams"][0]["room"], "Sala Sintética")
        self.assertIn(uid, [r["study_uid"] for r in p["received"]])
        self.assertGreaterEqual(len(p["reception_failures"]), 1)
        self.assertIn("no_order", next(q["issues"] for q in p["quality_issues"] if q["study_uid"] == uid))
        u = f"/api/v1/ris/schedules/{sid}/status"
        self.assertEqual(tec.patch(u, json={"status": "cancelled", "reason": "x"}).status_code, 403)
        for st in ("arrived", "in_progress"):
            self.assertEqual(tec.patch(u, json={"status": st}).status_code, 200)
        me = set(tec.get("/api/v1/auth/me").json()["permissions"])
        self.assertNotIn("report.sign", me)
        self.assertNotIn("ris.schedule.manage", me)
        self.assertEqual(tec.post("/api/v1/report/reports/finalize-batch",
                                  json={"report_ids": [str(sid)], "password": "x", "confirm": True}).status_code, 403)
        self.assertEqual(tec.patch(u, json={"status": "completed"}).status_code, 200)
        oid2, _, _ = make_order(self.t)
        with db.session(self.t) as s:
            sid2 = ris.schedule(s, oid2, scheduled_at=datetime(2026, 11, 30, 9, tzinfo=BRT), modality="CT",
                                actor="recep").id
        self.assertEqual(recep.patch(f"/api/v1/ris/schedules/{sid2}/status",
                                     json={"status": "cancelled", "reason": "paciente desmarcou"}).status_code, 200)
        self.assertEqual(self.login().get("/api/v1/ris/technician-panel",
                                          params={"day": date(2026, 11, 30).isoformat()}).json()["exams"][0]["status"],
                         "cancelled")


if __name__ == "__main__":
    unittest.main()
