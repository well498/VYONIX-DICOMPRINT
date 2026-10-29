"""Minha Produção: laudos liberados por médico (dia, mês, unidade, modalidade), pendências, tempo de conclusão,
exportação CSV/PDF sem dados de pacientes, permissões (própria × de todos × valores financeiros) e auditoria.
PostgreSQL real; dados sintéticos."""

from __future__ import annotations

import uuid
from datetime import date

from tests_platform.support import require_db
from tests_platform.test_pacs import ApiBase

PW = "Senha-Nova-9876!"


def setUpModule():
    global db
    db = require_db()
    from tests_platform import test_pacs, test_report
    test_pacs.db = test_report.db = db


class Production(ApiBase):
    def setUp(self):
        super().setUp()
        from vyonix.clinical import service as clinical
        from vyonix.modules import registry
        from vyonix.tenancy.models import Site
        doc = self.helper.issue("annual", modules={"core": {"kind": "contract"}, "report": {"kind": "contract"}})
        with db.session(self.t) as s:
            self.lic.install(s, doc["document"], actor="admin")
            registry.enable(s, "report", actor="admin", license_check=self.lic.module_ok)
            n = Site(name="Unidade Norte")
            s.add(n)
            s.flush()
            p = clinical.create_patient(s, name="Producao Sintetica Paciente", birth_date=date(1990, 1, 1), sex="F",
                                        identifiers=[("DICOM", "PROD-1")], actor="t")
            self.st = []
            for mod in ("CR", "CR", "CT", "MR"):
                st = clinical.register_study(s, study_instance_uid=f"2.25.{uuid.uuid4().int}", modality=mod,
                                             study_date=date(2026, 10, 28), site_id=n.id, actor="t")
                st.patient_id = p.id
                self.st.append(str(st.id))
        self.admin = self.login()
        self.docs = {}
        for name in ("dra_prod", "dr_outro"):
            uid = self.admin.post("/api/v1/users", json={"username": name, "display_name": name,
                                                          "password": "Senha-Teste-1234",
                                                          "roles": [{"role": "medico"}]}).json()["id"]
            c = self.login(name, "Senha-Teste-1234")
            c.post("/api/v1/auth/password", json={"current": "Senha-Teste-1234", "new": PW})
            pid = self.admin.post("/api/v1/report/physicians", json={
                "user_id": uid, "full_name": f"Dr(a). {name} Sintetico", "crm": str(2000 + len(self.docs)),
                "crm_uf": "PB"}).json()["id"]
            self.admin.post(f"/api/v1/report/physicians/{pid}/links", json={"site_id": None, "valid_from": "2026-01-01"})
            self.docs[name] = (self.login(name, PW), pid)

    def finalize(self, c, study_id):
        rep = c.post("/api/v1/report/reports", json={"study_id": study_id}).json()
        rep = c.put(f"/api/v1/report/reports/{rep['id']}", json={"body": "Achados: texto sintético.\nConclusão: teste.",
                                                                  "row_version": rep["row_version"]}).json()
        r = c.post(f"/api/v1/report/reports/{rep['id']}/finalize", json={"password": PW,
                                                                         "row_version": rep["row_version"]})
        self.assertEqual(r.status_code, 200, r.text)
        return rep["id"]

    def test_own_production_counts_pending_and_exports(self):
        me, pid = self.docs["dra_prod"]
        other, _ = self.docs["dr_outro"]
        for sid in self.st[:3]:
            self.finalize(me, sid)
        self.finalize(other, self.st[3])
        me.post("/api/v1/report/reports", json={"study_id": self.st[3]})          # rascunho dela (já liberado por outro)
        r = me.get("/api/v1/report/production")
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual(d["finalized"], 3)                                         # só os dela
        self.assertEqual(dict(d["by_modality"]), {"CR": 2, "CT": 1})
        self.assertEqual(dict(d["by_site"]), {"Unidade Norte": 3})
        self.assertEqual(sum(v for _k, v in d["by_day"]), 3)
        self.assertIsNotNone(d["turnaround_hours"]["mean"])
        self.assertFalse(d["financial"])
        self.assertNotIn("values", d)
        self.assertFalse(d["can_see_all"])
        # exportações sem dados de pacientes
        csv = me.get("/api/v1/report/production", params={"format": "csv"})
        self.assertEqual(csv.status_code, 200)
        text = csv.content.decode("utf-8")
        self.assertTrue(text.startswith("﻿"))
        self.assertIn("Laudos liberados;3", text)
        self.assertNotIn("Producao Sintetica", text)
        self.assertNotIn("PROD-1", text)
        pdf = me.get("/api/v1/report/production", params={"format": "pdf"})
        self.assertEqual((pdf.status_code, pdf.content[:5]), (200, b"%PDF-"))

    def test_permissions_other_physician_and_financial_values(self):
        me, pid = self.docs["dra_prod"]
        _, other_pid = self.docs["dr_outro"]
        self.finalize(me, self.st[0])
        self.finalize(me, self.st[2])
        # médico não vê produção de outro médico
        self.assertEqual(me.get("/api/v1/report/production", params={"physician_id": other_pid}).status_code, 403)
        self.assertEqual(me.get("/api/v1/report/production/physicians").status_code, 403)
        # administrador sem cadastro médico: não tem produção própria
        self.assertEqual(self.admin.get("/api/v1/report/production").status_code, 404)
        # administrador vê a de qualquer médico, com valores (tabela da instituição)
        r = self.admin.put("/api/v1/settings/report/production",
                           json={"value": {"values": [{"modality": "CR", "value_cents": 4550}]}, "reason": "teste"})
        self.assertEqual(r.status_code, 200, r.text)
        d = self.admin.get("/api/v1/report/production", params={"physician_id": pid}).json()
        self.assertEqual(d["finalized"], 2)
        self.assertTrue(d["financial"])
        self.assertEqual(d["values"]["total_cents"], 4550)
        self.assertEqual(d["values"]["missing"], ["CT"])                         # modalidade sem valor configurado
        self.assertIn("Valor (R$)", self.admin.get("/api/v1/report/production",
                                                   params={"physician_id": pid, "format": "csv"}).text)
        names = [x["name"] for x in self.admin.get("/api/v1/report/production/physicians").json()["items"]]
        self.assertIn("Dr(a). dra_prod Sintetico", names)
        from vyonix.audit import service as audit
        with db.session(self.t) as s:
            self.assertGreaterEqual(len(audit.query(s, action="report.production.view")), 2)

    def test_invalid_period(self):
        me, _ = self.docs["dra_prod"]
        r = me.get("/api/v1/report/production", params={"date_from": "2026-10-10", "date_to": "2026-10-01"})
        self.assertEqual(r.status_code, 422)
        r = me.get("/api/v1/report/production", params={"date_from": "2024-01-01", "date_to": "2026-10-01"})
        self.assertEqual(r.status_code, 422)
