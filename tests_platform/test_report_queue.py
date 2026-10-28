"""TELELAUDO T7 — fila de laudos: médico só vê e abre exames das unidades com vínculo vigente; coordenação vê
tudo e atribui; atribuição exige vínculo na unidade, prazo pela prioridade, reatribuição cancela a anterior e a
liberação conclui. PostgreSQL real; dados sintéticos."""

from __future__ import annotations

import unittest
import uuid
from datetime import date

from tests_platform.support import require_db
from tests_platform.test_pacs import ApiBase


def setUpModule():
    global db
    db = require_db()
    from tests_platform import test_pacs, test_report
    test_pacs.db = test_report.db = db


class Queue(ApiBase):
    def setUp(self):
        super().setUp()
        from vyonix.clinical import service as clinical
        from vyonix.modules import registry
        from vyonix.tenancy.models import Site
        doc = self.helper.issue("annual", modules={"core": {"kind": "contract"}, "report": {"kind": "contract"}})
        with db.session(self.t) as s:
            self.lic.install(s, doc["document"], actor="admin")
            registry.enable(s, "report", actor="admin", license_check=self.lic.module_ok)
            n, so = Site(name="Unidade Norte"), Site(name="Unidade Sul")
            s.add_all([n, so])
            s.flush()
            self.north, self.south = n.id, so.id
            p = clinical.create_patient(s, name="Fila Sintetica Teste", birth_date=date(1990, 1, 1), sex="M",
                                        identifiers=[("DICOM", "FILA-1")], actor="t")
            self.st = {}
            for key, site in (("n", n.id), ("s", so.id)):
                st = clinical.register_study(s, study_instance_uid=f"2.25.{uuid.uuid4().int}", modality="CR",
                                             study_date=date(2026, 10, 28), site_id=site, actor="t")
                st.patient_id = p.id
                self.st[key] = st.id
        self.admin = self.login()
        self.users = {}
        for name, link in (("dra_norte", self.north), ("dr_todas", None)):
            uid = self.admin.post("/api/v1/users", json={"username": name, "display_name": name,
                                                          "password": "Senha-Teste-1234",
                                                          "roles": [{"role": "medico"}]}).json()["id"]
            c = self.login(name, "Senha-Teste-1234")
            c.post("/api/v1/auth/password", json={"current": "Senha-Teste-1234", "new": "Senha-Nova-9876!"})
            pid = self.admin.post("/api/v1/report/physicians", json={
                "user_id": uid, "full_name": f"Dr(a). {name} Sintetico", "crm": str(1000 + len(self.users)),
                "crm_uf": "BA"}).json()["id"]
            self.admin.post(f"/api/v1/report/physicians/{pid}/links",
                            json={"site_id": str(link) if link else None, "valid_from": "2026-01-01"})
            self.users[name] = (self.login(name, "Senha-Nova-9876!"), pid, uuid.UUID(uid))

    def ids(self, c, **params):
        return {x["study_id"] for x in c.get("/api/v1/report/worklist", params=params).json()["items"]}

    def test_scope_by_unit(self):
        norte, todas = self.users["dra_norte"][0], self.users["dr_todas"][0]
        n, so = str(self.st["n"]), str(self.st["s"])
        self.assertEqual(self.ids(norte), {n})
        self.assertEqual(self.ids(todas), {n, so})
        self.assertTrue({n, so} <= self.ids(self.admin))                      # coordenação (report.assign)
        r = norte.post("/api/v1/report/reports", json={"study_id": so})
        self.assertEqual((r.status_code, r.json()["error"]), (403, "out_of_scope"))
        rid = todas.post("/api/v1/report/reports", json={"study_id": so}).json()["id"]
        for path in (f"/api/v1/report/reports/{rid}", f"/api/v1/report/reports/{rid}/verify"):
            self.assertEqual(norte.get(path).status_code, 403, path)          # nem por ID direto
        self.assertEqual(norte.get("/api/v1/report/suggest", params={"study_id": so}).status_code, 403)

    def test_assignment_sla_reassign_and_close(self):
        from datetime import datetime
        norte, pid_n, _ = self.users["dra_norte"]
        todas, pid_t, _ = self.users["dr_todas"]
        r = self.admin.post("/api/v1/report/assignments", json={"study_id": str(self.st["s"]), "physician_id": pid_n})
        self.assertEqual((r.status_code, r.json()["error"]), (403, "physician_not_linked"))
        self.assertEqual(norte.post("/api/v1/report/assignments", json={
            "study_id": str(self.st["n"]), "physician_id": pid_n}).status_code, 403)         # médico não distribui
        r = self.admin.post("/api/v1/report/assignments", json={"study_id": str(self.st["n"]), "physician_id": pid_t,
                                                                 "priority": "stat"})
        due = datetime.fromisoformat(r.json()["due_at"])
        self.assertAlmostEqual((due - datetime.now(due.tzinfo)).total_seconds(), 3600, delta=120)
        self.assertEqual(self.ids(todas, mine=True), {str(self.st["n"])})
        self.admin.post("/api/v1/report/assignments", json={"study_id": str(self.st["n"]), "physician_id": pid_n})
        self.assertEqual(self.ids(todas, mine=True), set())                   # reatribuído
        item = next(x for x in norte.get("/api/v1/report/worklist", params={"mine": True}).json()["items"])
        self.assertEqual((item["assignment"]["priority"], item["assignment"]["overdue"]), ("routine", False))
        rid = norte.post("/api/v1/report/reports", json={"study_id": str(self.st["n"])}).json()["id"]
        rv = norte.put(f"/api/v1/report/reports/{rid}", json={"body": "Texto."}).json()["row_version"]
        r = norte.post(f"/api/v1/report/reports/{rid}/finalize", json={"password": "Senha-Nova-9876!", "row_version": rv})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.ids(norte, mine=True), set())                   # liberado: atribuição concluída
        with db.session(self.t) as s:
            from sqlalchemy import select
            from vyonix.report.models import Assignment
            st = sorted(a.status for a in s.execute(select(Assignment)).scalars())
            self.assertEqual(st, ["cancelled", "done"])


if __name__ == "__main__":
    unittest.main()
