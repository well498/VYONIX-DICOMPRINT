"""Regressões de segurança dos laudos encontradas na auditoria A05 (29/10/2026).

A05-001: registrar a comunicação de um achado crítico exigia só ``report.write``: um médico comunicava alerta de outra
unidade e a resposta trazia os alertas abertos de TODAS as unidades (nome do paciente, nota, acesso).
A05-002: compartilhamento temporário com escopo ``view`` permitia editar e liberar o laudo."""

import unittest
import uuid
from datetime import date

from tests_platform import test_report_queue as tq
from tests_platform.support import require_db

PW = "Senha-Nova-9876!"


def setUpModule():
    global db
    db = require_db()
    from tests_platform import test_pacs, test_report
    test_pacs.db = test_report.db = tq.db = db


class ScopeSecurity(tq.Queue):
    # reutiliza só a preparação (unidades, médicos, estudos); os testes da classe base rodam no próprio módulo
    locals().update({n: None for n in dir(tq.Queue) if n.startswith("test_")})

    def _study(self, site):
        from vyonix.clinical import service as clinical
        with db.session(self.t) as s:
            st = clinical.register_study(s, study_instance_uid=f"2.25.{uuid.uuid4().int}", modality="CR",
                                         study_date=date(2026, 10, 28), site_id=site, actor="t")
            return str(st.id)

    def _critical(self, who, study, note):
        rid = who.post("/api/v1/report/reports", json={"study_id": study}).json()["id"]
        who.put(f"/api/v1/report/reports/{rid}", json={"body": "Achado.", "critical": True, "critical_note": note})
        r = who.post(f"/api/v1/report/reports/{rid}/finalize", json={"password": PW})
        self.assertEqual(r.status_code, 200, r.text)

    def test_a05_001_communicate_respects_site_scope(self):
        norte = self.users["dra_norte"][0]
        todas = self.users["dr_todas"][0]
        self._critical(todas, str(self.st["s"]), "ALERTA SUL")
        self._critical(norte, self._study(self.north), "ALERTA NORTE")
        sul = [x for x in todas.get("/api/v1/report/critical").json()["items"] if x["note"] == "ALERTA SUL"][0]
        r = norte.post(f"/api/v1/report/critical/{sul['id']}/communicate",
                       json={"notified_to": "Dr X", "channel": "telefone"})
        self.assertIn(r.status_code, (403, 404), r.text)          # alerta de outra unidade: recusado
        mine = [x for x in norte.get("/api/v1/report/critical").json()["items"] if x["note"] == "ALERTA NORTE"][0]
        r = norte.post(f"/api/v1/report/critical/{mine['id']}/communicate",
                       json={"notified_to": "Dr Y", "channel": "telefone"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn("ALERTA SUL", [x["note"] for x in r.json()["items"]])   # resposta filtrada pela unidade
        self.assertIn("ALERTA SUL", [x["note"] for x in todas.get("/api/v1/report/critical").json()["items"]])

    def test_a05_002_view_share_is_read_only(self):
        from vyonix.ris import prep
        norte, _pid, uid_n = self.users["dra_norte"]
        todas = self.users["dr_todas"][0]
        st = self._study(self.south)
        rid = todas.post("/api/v1/report/reports", json={"study_id": st}).json()["id"]
        todas.put(f"/api/v1/report/reports/{rid}", json={"body": "Rascunho da unidade Sul."})
        with db.session(self.t) as s:
            prep.share(s, uuid.UUID(st), uid_n, scope="view", hours=2, actor="admin")
        self.assertEqual(norte.get(f"/api/v1/report/reports/{rid}").status_code, 200)        # leitura permitida
        self.assertEqual(norte.put(f"/api/v1/report/reports/{rid}", json={"body": "x"}).status_code, 403)
        self.assertEqual(norte.post(f"/api/v1/report/reports/{rid}/finalize", json={"password": PW}).status_code, 403)
        self.assertEqual(norte.post(f"/api/v1/report/reports/{rid}/addenda", json={"text": "x", "password": PW}).status_code, 403)
        st2 = self._study(self.south)
        with db.session(self.t) as s:
            prep.share(s, uuid.UUID(st2), uid_n, scope="report", hours=2, actor="admin")
        r = norte.post("/api/v1/report/reports", json={"study_id": st2})               # escopo report: pode laudar
        self.assertIn(r.status_code, (200, 201), r.text)
        self.assertEqual(norte.put(f"/api/v1/report/reports/{r.json()['id']}", json={"body": "ok"}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
