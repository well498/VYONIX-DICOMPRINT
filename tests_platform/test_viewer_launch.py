"""VYONIX Viewer — lançador com protocolos de exibição, comparação com exame anterior autorizado, escopo opcional
das imagens por vínculo do médico (DICOMweb) e histórico integrado do paciente.

PostgreSQL real com o motor dublê do PACS (o Viewer em si — OHIF — é exercitado no CI ``viewer.yml``). Dados
sintéticos; não é validação clínica."""

from __future__ import annotations

import unittest
import uuid
from datetime import date
from urllib.parse import parse_qs, urlparse

import tests_platform.test_ris_prep as _prep
from tests_platform.pacs_support import uid
from tests_platform.support import require_db


def setUpModule():
    global db
    db = require_db()
    _prep.setUpModule()


def q(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


class ViewerLaunch(_prep.Prep):
    test_preparation_flow = test_reception_in_progress_duplicates_and_distribution = None  # só os testes abaixo
    test_reservation_expires_and_share_with_deadline = test_isolation_between_institutions = None

    def setUp(self):
        super().setUp()
        from sqlalchemy import update
        from vyonix.clinical.models import Study
        from vyonix.tenancy import service as tenancy
        with db.session(self.t) as s:
            self.site_a = tenancy.save_site(s, name="Unidade A Sintetica", actor="t").id
            self.site_b = tenancy.save_site(s, name="Unidade B Sintetica", actor="t").id
        self.old_a, self.old_b, self.cur = self.study(1), self.study(2), self.study(3)   # mesmo paciente
        self.mr = self.study(4)
        with db.session(self.t) as s:
            for sid, site, d, mod in ((self.old_a, self.site_a, date(2025, 3, 1), "CT"),
                                      (self.old_b, self.site_b, date(2025, 9, 1), "CT"),
                                      (self.cur, self.site_a, date(2026, 10, 28), "CT"),
                                      (self.mr, self.site_a, date(2026, 1, 10), "MR")):
                s.execute(update(Study).where(Study.id == uuid.UUID(sid)).values(site_id=site, study_date=d,
                                                                                   modality=mod))
        # médica só com vínculo na unidade A
        self.carla = self.user("carla", ["medico"])
        uid_ = next(u["id"] for u in self.admin.get("/api/v1/users").json() if u["username"] == "carla")
        pid = self.admin.post("/api/v1/report/physicians", json={"user_id": uid_, "full_name": "Dra. Carla Sintetica",
                                                                 "crm": "1003", "crm_uf": "PB"}).json()["id"]
        r = self.admin.post(f"/api/v1/report/physicians/{pid}/links", json={"valid_from": "2026-01-01",
                                                                            "site_id": str(self.site_a)})
        self.assertEqual(r.status_code, 201, r.text)
        self.ana = self.docs["ana"][0]
        self.U = {self.old_a: uid(71), self.old_b: uid(72), self.cur: uid(73), self.mr: uid(74)}

    def launch(self, c, sid, **params):
        return c.get("/api/v1/pacs/viewer/launch", params={"study_uid": self.U[sid], **params})

    def test_protocols_comparison_and_priors(self):
        r = self.launch(self.ana, self.cur)
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual((d["layout"], d["source"]), ("default", "default"))
        self.assertEqual(q(d["url"]), {"StudyInstanceUIDs": self.U[self.cur]})
        self.assertEqual([x["study_instance_uid"] for x in d["priors"]],
                         [self.U[self.mr], self.U[self.old_b], self.U[self.old_a]])          # mais recente primeiro
        # protocolo da instituição para CT: comparar com o anterior da mesma modalidade
        self.assertEqual(self.ana.post("/api/v1/pacs/viewer/protocols",
                                       json={"modality": "CT", "layout": "compare", "personal": False}).status_code, 403)
        r = self.admin.post("/api/v1/pacs/viewer/protocols", json={"modality": "ct", "layout": "compare",
                                                                    "personal": False})
        self.assertEqual(r.status_code, 201, r.text)
        d = self.launch(self.ana, self.cur).json()
        self.assertEqual((d["layout"], d["source"], d["prior"]["study_instance_uid"]),
                         ("compare", "institution", self.U[self.old_b]))                    # pula o MR (outra modalidade)
        self.assertEqual(q(d["url"]), {"StudyInstanceUIDs": f"{self.U[self.cur]},{self.U[self.old_b]}",
                                       "hangingprotocolId": "@ohif/hpCompare"})
        # escolha explícita de outro anterior do mesmo paciente
        d = self.launch(self.ana, self.cur, prior=self.U[self.old_a]).json()
        self.assertEqual(d["prior"]["study_instance_uid"], self.U[self.old_a])
        r = self.launch(self.ana, self.cur, prior=uid(99))                                  # não é anterior deste paciente
        self.assertEqual((r.status_code, r.json()["error"]), (403, "prior_not_allowed"))
        # protocolo pessoal tem precedência (se a instituição permitir)
        r = self.ana.post("/api/v1/pacs/viewer/protocols", json={"modality": "CT", "layout": "grid"})
        self.assertEqual(r.status_code, 201, r.text)
        mine = r.json()["id"]
        d = self.launch(self.ana, self.cur).json()
        self.assertEqual((d["layout"], d["source"], q(d["url"])["hangingprotocolId"]), ("grid", "personal", "@ohif/mnGrid"))
        self.assertEqual(self.launch(self.docs["bruno"][0], self.cur).json()["source"], "institution")   # só da Ana
        self.assertEqual(self.docs["bruno"][0].delete(f"/api/v1/pacs/viewer/protocols/{mine}").status_code, 404)
        from vyonix.settings import service as settings
        with db.session(self.t) as s:
            settings.put(s, "pacs", "viewer", {"access": "organization", "allow_personal": False}, actor="admin")
        self.assertEqual(self.launch(self.ana, self.cur).json()["source"], "institution")
        r = self.ana.post("/api/v1/pacs/viewer/protocols", json={"modality": "MR", "layout": "grid"})
        self.assertEqual((r.status_code, r.json()["error"]), (403, "personal_disabled"))
        # explícito vence tudo; comparação sem anterior volta ao padrão com aviso
        self.assertEqual(self.launch(self.ana, self.cur, layout="default").json()["layout"], "default")
        d = self.launch(self.ana, self.old_a, layout="compare").json()
        self.assertEqual((d["layout"], d["prior"]), ("default", None))
        self.assertIn("Sem exame anterior", d["note"])
        # auditoria do lançamento
        from vyonix.audit import service as audit
        with db.session(self.t) as s:
            self.assertTrue(audit.query(s, action="pacs.viewer.launch"))
        # técnico sem pacs.studies.read? (técnico tem) — recepção não abre imagens
        recep = self.user("recep1", ["recepcionista"])
        self.assertEqual(self.launch(recep, self.cur).status_code, 403)

    def test_linked_access_limits_dicomweb_and_comparison(self):
        DW = "/api/v1/pacs/dicomweb"
        qido = lambda c: sorted(x["0020000D"]["Value"][0] for x in (c.get(DW + "/studies").json()  # noqa: E731
                                                                    if c.get(DW + "/studies").status_code == 200 else []))
        all4 = sorted(self.U.values())
        self.assertEqual(qido(self.carla), all4)                    # padrão homologado: organização inteira
        from vyonix.settings import service as settings
        with db.session(self.t) as s:
            settings.put(s, "pacs", "viewer", {"access": "linked", "allow_personal": True}, actor="admin",
                         reason="teste do escopo por vínculo")
        self.assertEqual(qido(self.carla), sorted(self.U[x] for x in (self.old_a, self.cur, self.mr)))
        self.assertEqual(qido(self.ana), all4)                      # vínculo com a organização inteira
        self.assertEqual(qido(self.admin), all4)                    # administração do PACS
        self.assertEqual(self.carla.get(f"{DW}/studies/{self.U[self.old_b]}/metadata").status_code, 404)
        self.assertEqual(self.carla.get(f"{DW}/studies/{self.U[self.old_b]}/series").status_code, 404)
        self.assertEqual(self.carla.get(f"{DW}/studies/{self.U[self.cur]}/metadata").status_code, 200)
        d = self.launch(self.carla, self.cur, layout="compare").json()
        self.assertNotIn(self.U[self.old_b], [x["study_instance_uid"] for x in d["priors"]])
        self.assertEqual(d["prior"]["study_instance_uid"], self.U[self.old_a])
        r = self.launch(self.carla, self.cur, prior=self.U[self.old_b])
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.launch(self.carla, self.old_b).status_code, 404)
        # compartilhamento temporário libera o estudo para ela
        carla_id = next(u["id"] for u in self.admin.get("/api/v1/users").json() if u["username"] == "carla")
        r = self.coord.post(f"/api/v1/ris/prep/{self.old_b}/shares", json={"user_id": carla_id, "scope": "view",
                                                                           "hours": 2})
        self.assertIn(r.status_code, (200, 201), r.text)
        self.assertEqual(self.carla.get(f"{DW}/studies/{self.U[self.old_b]}/metadata").status_code, 200)

    def test_patient_history_integrated_without_duplicates(self):
        from vyonix.clinical import service as clinical
        from vyonix.clinical.models import Study
        with db.session(self.t) as s:
            o = clinical.create_order(s, patient_id=self.pat, requester="Dr. Solicitante Sintetico", actor="t")
            s.get(Study, uuid.UUID(self.cur)).order_id = o.id                 # pedido ligado ao estudo atual
            enc = clinical.create_encounter(s, patient_id=self.pat, site_id=self.site_a, actor="t")
            o2 = clinical.create_order(s, patient_id=self.pat, encounter_id=enc.id, requester="Dr. Outro", actor="t")
            o2_id = str(o2.id)
            clinical.create_encounter(s, patient_id=self.pat, site_id=self.site_b, actor="t")   # atendimento sem pedido
        rep = self.ana.post("/api/v1/report/reports", json={"study_id": self.old_a}).json()
        r = self.ana.get(f"/api/v1/ris/patients/{self.pat}/history")
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        kinds = [(x["kind"], x.get("study_id")) for x in d["items"]]
        self.assertEqual(sum(1 for k in kinds if k[0] == "study"), 4)
        self.assertEqual(d["counts"], {"studies": 4, "orders_without_study": 1, "encounters_without_order": 1})
        cur = next(x for x in d["items"] if x.get("study_id") == self.cur)
        self.assertEqual((cur["requester"], cur["study_instance_uid"], cur["images"]["series"]),
                         ("Dr. Solicitante Sintetico", self.U[self.cur], 1))
        old = next(x for x in d["items"] if x.get("study_id") == self.old_a)
        self.assertEqual((old["report"]["id"], old["report"]["status"]), (rep["id"], "draft"))
        order = next(x for x in d["items"] if x["kind"] == "order")
        self.assertEqual((order["requester"], order["encounter"]["status"]), ("Dr. Outro", "open"))
        self.assertTrue(o2_id)
        self.assertEqual(d["items"][0]["date"] >= d["items"][-1]["date"], True)          # mais recente primeiro
        self.assertNotIn("Achados", r.text)                                              # sem texto de laudo
        # médica com vínculo só na unidade A: exame da unidade B aparece restrito
        dc = self.carla.get(f"/api/v1/ris/patients/{self.pat}/history").json()
        b = next(x for x in dc["items"] if x.get("study_id") == self.old_b)
        self.assertTrue(b["restricted"])
        self.assertNotIn("study_instance_uid", b)
        self.assertNotIn("report", b)
        # quem não lê pacientes não vê o histórico; outra organização não acha o paciente
        self.assertEqual(self.login().get(f"/api/v1/ris/patients/{uuid.uuid4()}/history").status_code, 404)
        from tests_platform.support import new_org
        from vyonix.ris import timeline
        other = new_org(db)
        with db.session(other) as s:
            from vyonix.errors import NotFound
            with self.assertRaises(NotFound):
                timeline.patient_history(s, self.pat)


if __name__ == "__main__":
    unittest.main()
