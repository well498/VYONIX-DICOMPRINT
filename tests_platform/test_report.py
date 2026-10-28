"""VYONIX REPORT — laudos: modelos, rascunho, liberação com confirmação de senha, versão imutável com SHA-256,
adendos, achado crítico, verificação, isolamento entre organizações e permissões por papel.
PostgreSQL real (row level security); dados sintéticos."""

from __future__ import annotations

import secrets
import unittest
import uuid
from datetime import date

from tests_platform.support import ADMIN_PW, new_org, require_db


def setUpModule():
    global db
    db = require_db()
    from tests_platform import test_pacs
    test_pacs.db = db


def make_study(tid, *, modality="CT", with_order=True):
    from vyonix.clinical import service as clinical
    acc = None
    with db.session(tid) as s:
        p = clinical.create_patient(s, name="Laudo Sintetico Teste", birth_date=date(1970, 3, 4), sex="F",
                                    identifiers=[("DICOM", f"L{secrets.token_hex(3).upper()}")], actor="t")
        oid = None
        if with_order:
            o = clinical.create_order(s, patient_id=p.id, requester="Dr. Solicitante", actor="t")
            oid, acc = o.id, o.accession
        st = clinical.register_study(s, study_instance_uid=f"2.25.{uuid.uuid4().int}", accession=acc,
                                     modality=modality, study_date=date(2026, 10, 28), actor="t")
        if oid:
            clinical.reconcile(s, st.id, oid, actor="t")
        return st.id, oid


def make_physician(tid, name="Dra. Ana Sintetica Medica", crm="123456", uf="CE", *, site_id=None, link=True):
    from datetime import date as d
    from vyonix.auth import service as auth
    from vyonix.report import physicians
    with db.session(tid) as s:
        auth.ensure_default_roles(s)
        u = auth.create_user(s, username=f"med{secrets.token_hex(3)}", display_name=name,
                             password="Senha-Teste-1234", roles=[("medico", None)], actor="t")
        p = physicians.save(s, user_id=u.id, full_name=name, crm=crm, crm_uf=uf, rqe="7788", actor="t")
        if link:
            physicians.add_link(s, p.id, site_id=site_id, valid_from=d(2026, 1, 1), actor="t")
        return u.id, p.id


class Service(unittest.TestCase):
    def setUp(self):
        from vyonix.report import service as rep
        self.rep = rep
        self.t = new_org(db)
        self.uid, self.pid = make_physician(self.t)
        self.who = "Dra. Ana Sintetica Medica — CRM 123456/CE — RQE 7788"

    def test_draft_finalize_addendum_and_integrity(self):
        from sqlalchemy import text
        from vyonix.audit import service as audit
        from vyonix.clinical.models import Order
        from vyonix.errors import Conflict, ValidationFailed
        from vyonix.events.models import OutboxEvent
        study_id, oid = make_study(self.t)
        with db.session(self.t) as s:
            t = self.rep.save_template(s, name="TC de crânio normal", modality="ct",
                                       body="Técnica: ...\nAchados: sem alterações.\nConclusão: ...", actor="med")
            from vyonix.report import templates as tpl
            tpl.publish(s, t.id, reviewed=True, actor="med")
            r = self.rep.open_report(s, study_id, template_id=t.id, actor="med")
            rid = r.id
            self.assertEqual((r.status, r.version), ("draft", 0))
            self.assertIn("Achados", r.body)
            self.assertEqual(self.rep.open_report(s, study_id, actor="outro").id, rid)       # um laudo por estudo
            with self.assertRaises(ValidationFailed):
                self.rep.update_draft(s, rid, body="x", critical=True, actor="med") and \
                    self.rep.finalize(s, rid, actor="Dra. Médica", actor_id=self.uid)                          # crítico sem descrição
        with db.session(self.t) as s:
            r = self.rep.update_draft(s, rid, body="Achados: nódulo de 8 mm.\nConclusão: controle.", critical=True,
                                      critical_note="Nódulo novo — avisar solicitante", actor="med")
            with self.assertRaises(Conflict):
                self.rep.update_draft(s, rid, body="y", expected_version=r.row_version - 1, actor="med")
        with db.session(self.t) as s:
            r = self.rep.finalize(s, rid, actor="Dra. Médica", actor_id=self.uid)
            self.assertEqual((r.status, r.version, r.finalized_by), ("final", 1, self.who))
            self.assertEqual(s.get(Order, oid).status, "completed")
            with self.assertRaises(Conflict):
                self.rep.update_draft(s, rid, body="mudar depois de liberado", actor="med")
            with self.assertRaises(Conflict):
                self.rep.finalize(s, rid, actor="Dra. Médica", actor_id=self.uid)
            v2 = self.rep.addendum(s, rid, "Adendo: comparado com exame anterior, estável.", actor="Dra. Médica",
                                 actor_id=self.uid)
            self.assertEqual((v2.version, v2.kind), (2, "addendum"))
        with db.session(self.t) as s:
            d = self.rep.get(s, rid)
            self.assertEqual([(v["version"], v["kind"]) for v in d["versions"]], [(1, "final"), (2, "addendum")])
            self.assertEqual(d["versions"][0]["body"], "Achados: nódulo de 8 mm.\nConclusão: controle.")
            self.assertTrue(self.rep.verify(s, rid)["valid"])
            types = [e.type for e in s.query(OutboxEvent).filter(OutboxEvent.subject_id == str(rid))]
            self.assertEqual(sorted(types), ["report.amended.v1", "report.critical.v1", "report.finalized.v1"])
            self.assertEqual(len(audit.query(s, action="report.finalize")), 1)
            for e in s.query(OutboxEvent).filter(OutboxEvent.subject_id == str(rid)):
                self.assertNotIn("Sintetico", str(e.data))                                 # sem dados do paciente
        # alteração direta no banco (fora da aplicação) é detectada pela verificação
        from sqlalchemy import create_engine
        from tests_platform.support import urls
        eng = create_engine(urls().owner.replace("postgresql://", "postgresql+psycopg://", 1))
        try:
            with eng.begin() as cx:                                          # dono do banco, fora da aplicação
                cx.execute(text("SELECT set_config('vyonix.tenant_id', :t, true)"), {"t": str(self.t)})
                cx.execute(text("UPDATE report.report_versions SET body = body || ' (alterado)' "
                                "WHERE report_id = :r AND version = 1"), {"r": rid})
        finally:
            eng.dispose()
        with db.session(self.t) as s:
            v = self.rep.verify(s, rid)
            self.assertEqual((v["valid"], v["altered"]), (False, [1]))

    def test_critical_alert_lifecycle(self):
        from vyonix.errors import Conflict, ValidationFailed
        study_id, _ = make_study(self.t)
        with db.session(self.t) as s:
            r = self.rep.open_report(s, study_id, actor="med")
            self.rep.update_draft(s, r.id, body="Pneumotórax extenso.", critical=True,
                                  critical_note="Pneumotórax — avisar plantão", actor="med")
            self.rep.finalize(s, r.id, actor="Dra. Médica", actor_id=self.uid)
            self.rep.addendum(s, r.id, "Novo achado crítico no adendo.", critical=True, actor="Dra. Médica",
                             actor_id=self.uid)
            open_ = self.rep.critical_alerts(s)
            self.assertEqual([(a["version"], a["note"]) for a in open_],
                             [(1, "Pneumotórax — avisar plantão"), (2, "Novo achado crítico no adendo.")])
            self.assertEqual(open_[0]["patient_name"], "Laudo Sintetico Teste")
            with self.assertRaises(ValidationFailed):
                self.rep.communicate(s, uuid.UUID(open_[0]["id"]), notified_to="", channel="telefone", actor="med")
            with self.assertRaises(ValidationFailed):
                self.rep.communicate(s, uuid.UUID(open_[0]["id"]), notified_to="Dr. X", channel="pombo", actor="med")
            a = self.rep.communicate(s, uuid.UUID(open_[0]["id"]), notified_to="Dr. Solicitante (plantão)",
                                     channel="telefone", note="Ciente às 10h", actor="Dra. Médica")
            self.assertEqual((a.status, a.ack_by), ("communicated", "Dra. Médica"))
            with self.assertRaises(Conflict):
                self.rep.communicate(s, a.id, notified_to="Dr. Y", channel="telefone", actor="med")
            self.assertEqual(len(self.rep.critical_alerts(s)), 1)
            self.assertEqual(len(self.rep.critical_alerts(s, status=None)), 2)

    def test_versions_immutable_for_application_role(self):
        from sqlalchemy import text
        from sqlalchemy.exc import ProgrammingError
        study_id, _ = make_study(self.t)
        with db.session(self.t) as s:
            r = self.rep.open_report(s, study_id, actor="med")
            self.rep.update_draft(s, r.id, body="Texto", actor="med")
            self.rep.finalize(s, r.id, actor="med", actor_id=self.uid)
            rid = r.id
        with self.assertRaises(ProgrammingError):                            # sem permissão de UPDATE na versão
            with db.session(self.t) as s:
                s.execute(text("UPDATE report.report_versions SET body = 'x' WHERE report_id = :r"), {"r": rid})
        with self.assertRaises(ProgrammingError):
            with db.session(self.t) as s:
                s.execute(text("DELETE FROM report.report_versions WHERE report_id = :r"), {"r": rid})

    def test_worklist_and_isolation(self):
        a, _ = make_study(self.t, modality="MR")
        b, _ = make_study(self.t, modality="CT")
        with db.session(self.t) as s:
            r = self.rep.open_report(s, b, actor="med")
            self.rep.update_draft(s, r.id, body="t", actor="med")
            st = {x["study_id"]: x["report_status"] for x in self.rep.worklist(s)}
            self.assertEqual((st[str(a)], st[str(b)]), ("pending", "draft"))
            self.assertEqual([x["study_id"] for x in self.rep.worklist(s, status="pending")], [str(a)])
            self.assertEqual([x["modality"] for x in self.rep.worklist(s, modality="mr")], ["MR"])
        other = new_org(db)
        with db.session(other) as s:
            self.assertEqual(self.rep.worklist(s), [])
            from vyonix.errors import NotFound
            with self.assertRaises(NotFound):
                self.rep.get(s, r.id)


class Physicians(unittest.TestCase):
    """TELELAUDO T1: cadastro de médicos, vínculos com vigência por unidade e regra de liberação."""

    def setUp(self):
        from vyonix.report import physicians, service as rep
        self.ph, self.rep = physicians, rep
        self.t = new_org(db)

    def test_validations_and_uniqueness(self):
        from vyonix.errors import Conflict, NotFound, ValidationFailed
        uid, pid = make_physician(self.t, crm="1111", uf="SP")
        uid2, _ = make_physician(self.t, name="Dr. Bruno Sintetico", crm="2222", uf="SP", link=False)
        with db.session(self.t) as s:
            for kw in ({"crm_uf": "XX"}, {"crm": "abc"}, {"full_name": "Dr"}):
                with self.assertRaises(ValidationFailed, msg=kw):
                    self.ph.save(s, **({"user_id": uid2, "full_name": "Dr. Bruno Sintetico", "crm": "3333",
                                        "crm_uf": "SP"} | kw), actor="t")
            with self.assertRaises(Conflict):                                   # CRM/UF repetido
                self.ph.save(s, user_id=uid2, full_name="Dr. Bruno Sintetico", crm="1.111", crm_uf="sp", actor="t")
            with self.assertRaises(Conflict):                                   # usuário já é médico
                self.ph.save(s, user_id=uid, full_name="Outro Nome Qualquer", crm="9999", crm_uf="SP", actor="t")
        other = new_org(db)
        with db.session(other) as s:                                            # usuário de outra organização
            with self.assertRaises(NotFound):
                self.ph.save(s, user_id=uid, full_name="Dra. Ana Sintetica Medica", crm="1111", crm_uf="SP",
                             actor="t")
            self.assertEqual(self.ph.listing(s), [])

    def test_release_requires_active_physician_with_valid_link_for_site(self):
        from datetime import date as d
        from vyonix.clinical.models import Study
        from vyonix.errors import Forbidden
        from vyonix.tenancy.models import Site
        with db.session(self.t) as s:
            a, b = Site(name="Unidade Norte"), Site(name="Unidade Sul")
            s.add_all([a, b])
            s.flush()
            site_a, site_b = a.id, b.id
        uid, pid = make_physician(self.t, link=False)
        study_id, _ = make_study(self.t)
        with db.session(self.t) as s:
            s.get(Study, study_id).site_id = site_b
            r = self.rep.open_report(s, study_id, actor="med")
            self.rep.update_draft(s, r.id, body="Texto", actor="med")
            rid = r.id

        def release():
            with db.session(self.t) as s:
                return self.rep.finalize(s, rid, actor="med", actor_id=uid)
        with self.assertRaises(Forbidden) as cm:
            release()
        self.assertEqual(cm.exception.code, "physician_not_linked")
        with db.session(self.t) as s:
            self.ph.add_link(s, pid, site_id=site_a, valid_from=d(2026, 1, 1), actor="t")            # outra unidade
            self.ph.add_link(s, pid, site_id=None, valid_from=d(2025, 1, 1), valid_to=d(2025, 12, 31), actor="t")
        with self.assertRaises(Forbidden):                                      # unidade errada e vínculo vencido
            release()
        with db.session(self.t) as s:
            self.ph.save(s, physician_id=pid, user_id=uid, full_name="Dra. Ana Sintetica Medica", crm="123456",
                         crm_uf="CE", active=False, actor="t")
            self.ph.add_link(s, pid, site_id=site_b, valid_from=d(2026, 1, 1), actor="t")
        with self.assertRaises(Forbidden) as cm:                                # cadastro inativo
            release()
        self.assertEqual(cm.exception.code, "physician_required")
        with db.session(self.t) as s:
            self.ph.save(s, physician_id=pid, user_id=uid, full_name="Dra. Ana Sintetica Medica", crm="123456",
                         crm_uf="CE", rqe="7788", actor="t")
        self.assertEqual(release().finalized_by, "Dra. Ana Sintetica Medica — CRM 123456/CE — RQE 7788")
        with db.session(self.t) as s:
            self.assertTrue(self.rep.verify(s, rid)["valid"])


from tests_platform.test_pacs import ApiBase  # noqa: E402


class Api(ApiBase):
    def license_report(self):
        from vyonix.modules import registry
        doc = self.helper.issue("annual", modules={"core": {"kind": "contract"}, "report": {"kind": "contract"}})
        with db.session(self.t) as s:
            self.lic.install(s, doc["document"], actor="admin")
            registry.enable(s, "report", actor="admin", license_check=self.lic.module_ok)

    def user(self, c, username, role):
        r = c.post("/api/v1/users", json={"username": username, "display_name": f"Dr(a). {username}",
                                          "password": "Senha-Teste-1234", "roles": [{"role": role}]})
        self.assertEqual(r.status_code, 201, r.text)
        self.ids = getattr(self, "ids", {})
        self.ids[username] = r.json()["id"]
        u = self.login(username, "Senha-Teste-1234")
        u.post("/api/v1/auth/password", json={"current": "Senha-Teste-1234", "new": "Senha-Nova-9876!"})
        return self.login(username, "Senha-Nova-9876!")

    def test_flow_with_password_confirmation_and_roles(self):
        from vyonix.audit import service as audit
        admin = self.login()
        study_id, _ = make_study(self.t)
        r = admin.post("/api/v1/report/reports", json={"study_id": str(study_id)})
        self.assertEqual((r.status_code, r.json()["error"]), (402, "module_disabled"))
        self.license_report()
        med = self.user(admin, "medica", "medico")
        tec = self.user(admin, "tecnico", "tecnico")
        r = admin.post("/api/v1/report/physicians", json={"user_id": self.ids["medica"], "full_name": "Dra. Medica Teste",
                                                          "crm": "54.321", "crm_uf": "pb", "specialties": ["Radiologia"]})
        self.assertEqual(r.status_code, 201, r.text)
        pid = r.json()["id"]
        self.assertEqual(med.get("/api/v1/report/physicians").status_code, 403)          # médico não gerencia cadastro
        r = med.post("/api/v1/report/templates", json={"name": "Normal", "body": "Sem alterações."})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(med.post(f"/api/v1/report/templates/{r.json()['id']}/publish", json={}).status_code, 422)
        self.assertEqual(med.post(f"/api/v1/report/templates/{r.json()['id']}/publish",
                                  json={"reviewed": True}).status_code, 200)
        tpl = med.get("/api/v1/report/templates", params={"published": True}).json()["items"][0]
        r = med.post("/api/v1/report/reports", json={"study_id": str(study_id), "template_id": tpl["id"]})
        self.assertEqual(r.status_code, 201, r.text)
        rep = r.json()
        self.assertEqual(rep["body"], "Achados:\nSem alterações.")
        self.assertEqual(tec.get(f"/api/v1/report/reports/{rep['id']}").status_code, 403)       # técnico não lê
        r = med.put(f"/api/v1/report/reports/{rep['id']}", json={"body": "Exame normal.",
                                                                 "row_version": rep["row_version"]})
        self.assertEqual(r.status_code, 200, r.text)
        rv = r.json()["row_version"]
        self.assertEqual(med.get(f"/api/v1/report/reports/{rep['id']}/pdf").status_code, 409)     # rascunho
        r = med.post(f"/api/v1/report/reports/{rep['id']}/finalize", json={"password": "Senha-Nova-9876!",
                                                                           "row_version": rv})
        self.assertEqual((r.status_code, r.json()["error"]), (403, "physician_not_linked"))       # sem vínculo
        self.assertEqual(admin.post(f"/api/v1/report/physicians/{pid}/links",
                                    json={"valid_from": "2026-01-01"}).status_code, 201)
        r = med.post(f"/api/v1/report/reports/{rep['id']}/finalize", json={"password": "errada", "row_version": rv})
        self.assertEqual((r.status_code, r.json()["error"]), (403, "password_mismatch"))
        self.assertEqual(med.get(f"/api/v1/report/reports/{rep['id']}").json()["status"], "draft")
        r = med.post(f"/api/v1/report/reports/{rep['id']}/finalize", json={"password": "Senha-Nova-9876!",
                                                                           "row_version": rv})
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual((d["status"], d["finalized_by"], len(d["versions"])), ("final", "Dra. Medica Teste — CRM 54321/PB", 1))
        self.assertEqual(len(d["versions"][0]["sha256"]), 64)
        self.assertEqual(med.put(f"/api/v1/report/reports/{rep['id']}", json={"body": "x"}).status_code, 409)
        r = med.post(f"/api/v1/report/reports/{rep['id']}/addenda",
                     json={"text": "Adendo sintético.", "password": "Senha-Nova-9876!"})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertTrue(med.get(f"/api/v1/report/reports/{rep['id']}/verify").json()["valid"])
        r = med.get(f"/api/v1/report/reports/{rep['id']}/pdf")
        self.assertEqual((r.status_code, r.headers["content-type"]), (200, "application/pdf"))
        self.assertIn("attachment", r.headers["content-disposition"])
        import io
        from pypdf import PdfReader
        txt = " ".join(pg.extract_text() for pg in PdfReader(io.BytesIO(r.content)).pages)
        for want in ("Laudo Sintetico Teste", "Exame normal.", "Adendo sintético.", "CRM 54321/PB",
                     "Não é assinatura digital", d["versions"][0]["sha256"][:16]):
            self.assertIn(want, txt.replace("\n", " "))
        self.assertEqual(tec.get(f"/api/v1/report/reports/{rep['id']}/pdf").status_code, 403)
        wl = med.get("/api/v1/report/worklist", params={"status": "final"}).json()["items"]
        self.assertEqual([x["report_id"] for x in wl], [rep["id"]])
        with db.session(self.t) as s:
            self.assertEqual(len(audit.query(s, action="auth.confirm_failed")), 1)
        # tentativa e erro com a sessão aberta: bloqueia após 5 senhas incorretas em 15 minutos
        for _ in range(4):
            self.assertEqual(med.post(f"/api/v1/report/reports/{rep['id']}/addenda",
                                      json={"text": "x", "password": "errada"}).json()["error"], "password_mismatch")
        r = med.post(f"/api/v1/report/reports/{rep['id']}/addenda", json={"text": "x", "password": "Senha-Nova-9876!"})
        self.assertEqual((r.status_code, r.json()["error"]), (403, "too_many_attempts"))


if __name__ == "__main__":
    unittest.main()
