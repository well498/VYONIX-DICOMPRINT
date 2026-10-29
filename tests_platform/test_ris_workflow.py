"""Fluxo do exame configurável (ris/workflow: agendamento e worklist com dependência) e linha do tempo do exame
(etapas, horários e responsáveis a partir dos registros do sistema, sem textos clínicos). PostgreSQL real; dados
sintéticos."""

from __future__ import annotations

import unittest
from datetime import datetime

from tests_platform.support import new_org, require_db


def setUpModule():
    global db
    db = require_db()
    from tests_platform import test_pacs, test_ris, test_ris_prep
    test_pacs.db = test_ris.db = test_ris_prep.db = db


class Workflow(unittest.TestCase):
    def test_scheduling_off_refuses_and_dependencies_enforced(self):
        from vyonix.errors import ValidationFailed
        from vyonix.ris import service as ris
        from vyonix.settings import service as settings
        from tests_platform.test_ris import BRT, make_order
        t = new_org(db)
        oid, _, _ = make_order(t)
        with db.session(t) as s:
            self.assertEqual(ris.workflow(s), {"scheduling": True, "worklist": True})       # padrão: tudo ligado
            with self.assertRaises(ValidationFailed):                     # worklist sem agendamento: dependência
                settings.put(s, "ris", "workflow", {"scheduling": False, "worklist": True}, actor="admin")
            settings.put(s, "ris", "workflow", {"scheduling": False, "worklist": False}, actor="admin",
                         reason="Clínica com fluxo simplificado")
        with db.session(t) as s:
            with self.assertRaises(ValidationFailed) as cm:
                ris.schedule(s, oid, scheduled_at=datetime(2026, 11, 3, 9, 0, tzinfo=BRT), modality="CT",
                             actor="recep")
            self.assertIn("Fluxo do exame", str(cm.exception))
            settings.put(s, "ris", "workflow", {"scheduling": True, "worklist": False}, actor="admin")
        with db.session(t) as s:
            ris.schedule(s, oid, scheduled_at=datetime(2026, 11, 3, 9, 0, tzinfo=BRT), modality="CT", actor="recep")


import tests_platform.test_ris_prep as _prep  # noqa: E402 (módulo, para não repetir os testes da preparação)


class Timeline(_prep.Prep):
    test_preparation_flow = test_reception_in_progress_duplicates_and_distribution = None  # só os testes abaixo
    test_reservation_expires_and_share_with_deadline = test_isolation_between_institutions = None

    def test_timeline_stages_actors_and_no_clinical_text(self):
        sid = self.study(1)
        u = f"/api/v1/ris/prep/{sid}"
        self.tec.post(u + "/comments", json={"text": "Texto clínico sintético que não deve aparecer."})
        for code in ("patient_identity", "procedure", "quality"):
            self.tec.post(u + "/check", json={"code": code})
        self.assertEqual(self.tec.post(u + "/forward").status_code, 200)
        _, pid, _ = self.docs["ana"]
        r = self.admin.post("/api/v1/report/assignments", json={"study_id": sid, "physician_id": pid})
        self.assertIn(r.status_code, (200, 201), r.text)
        t = self.tec.get(f"/api/v1/ris/studies/{sid}/timeline")
        self.assertEqual(t.status_code, 200, t.text)
        d = t.json()
        done = {x["code"] for x in d["stages"] if x["done"]}
        self.assertTrue({"pacs", "preparation", "distribution"} <= done, done)
        self.assertEqual(d["current"], "distribution")
        texts = [(e["text"], e["by"]) for e in d["events"]]
        self.assertIn(("Encaminhado para laudo", "tec1"), texts)
        self.assertIn(("Atribuído a médico", "admin"), texts)
        self.assertEqual(d["events"][0]["text"], "Primeiras imagens recebidas no PACS")
        self.assertNotIn("Texto clínico sintético", t.text)
        r = self.tec.get("/api/v1/ris/studies/00000000-0000-0000-0000-000000000000/timeline")
        self.assertIn(r.status_code, (403, 404))

    def test_priors_of_same_patient(self):
        old, new = self.study(1), self.study(2)                     # mesmo paciente (dados sintéticos)
        ana = self.docs["ana"][0]
        rep = ana.post("/api/v1/report/reports", json={"study_id": old}).json()
        rep = ana.put(f"/api/v1/report/reports/{rep['id']}", json={"body": "Achados: sintético.",
                                                                   "row_version": rep["row_version"]}).json()
        r = ana.post(f"/api/v1/report/reports/{rep['id']}/finalize", json={"password": _prep.NEW,
                                                                          "row_version": rep["row_version"]})
        self.assertEqual(r.status_code, 200, r.text)
        d = ana.get(f"/api/v1/ris/studies/{new}/priors").json()
        self.assertTrue(d["patient_linked"])
        self.assertEqual([x["study_id"] for x in d["items"]], [old])
        it = d["items"][0]
        self.assertEqual((it["modality"], it["same_modality"], it["report"]["status"]), ("CT", True, "final"))
        self.assertEqual(it["study_instance_uid"], _prep.uid(71))                # imagens no PACS: abre no Viewer
        self.assertEqual(self.tec.get(f"/api/v1/ris/studies/{old}/priors").json()["items"][0]["study_id"], new)


if __name__ == "__main__":
    unittest.main()
