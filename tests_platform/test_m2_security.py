"""MISSÃO 2 — testes de proteção das correções de segurança (dados sintéticos, PostgreSQL local de testes).

Cada teste mostra que o controle RECUSA a operação indevida (e, quando cabe, que a legítima continua permitida):

* R-01  médico não responsável não lê o rascunho, não edita, não envia para revisão, não libera (nem em lote) e
        não registra adendo no laudo de outro médico;
* R-02  médico não inicia o laudo de exame atribuído a outro (e o registro de início não é criado);
* R-03  médico não devolve para correção o exame de outro;
* R-04  técnico com papel numa unidade não age em exame de outra unidade nem em exame sem unidade;
* R-05  conciliar com pedido de outra prioridade não altera a prioridade depois do início do laudo;
* R-07  salvar ou liberar laudo sem ``row_version`` é recusado;
* S-01  administrador de uma unidade não se promove a global, não altera os próprios papéis e não redefine a senha
        do administrador da instituição;
* S-02  papel de uma unidade não lista estudos de outra, não altera configuração da instituição nem lê a auditoria;
* S-04  sair do sistema revoga as credenciais do visualizador externo;
* B-04  o papel da aplicação não altera a versão das migrações.
"""
from __future__ import annotations

import uuid

import tests_platform.test_ris_prep as _prep

PW, NEW = _prep.PW, _prep.NEW


def setUpModule():
    _prep.setUpModule()


class M2Security(_prep.Prep):
    locals().update({n: None for n in dir(_prep.Prep) if n.startswith("test_")})   # só os testes desta classe

    # ------------------------------------------------------------------ apoio
    def ready(self, n=1, physician="ana"):
        sid = self.study(n)
        u = f"/api/v1/ris/prep/{sid}"
        for code in ("patient_identity", "procedure", "quality"):
            self.tec.post(u + "/check", json={"code": code})
        self.assertEqual(self.tec.post(u + "/forward").status_code, 200)
        pid = self.docs[physician][1]
        r = self.tec.post(u + "/physician", json={"physician_id": pid, "reason": "escala sintética"})
        self.assertEqual(r.status_code, 200, r.text)
        return sid, u

    def rv(self, c, rid):
        return c.get(f"/api/v1/report/reports/{rid}").json()["row_version"]

    def site(self, name):
        r = self.admin.post("/api/v1/sites", json={"name": name})
        self.assertIn(r.status_code, (200, 201), r.text)
        return r.json()["id"]

    def site_user(self, login, role, site_id):
        r = self.admin.post("/api/v1/users", json={"username": login, "display_name": login, "password": PW,
                                                   "roles": [{"role": role, "site_id": site_id}]})
        self.assertEqual(r.status_code, 201, r.text)
        c = self.login(login, PW)
        c.post("/api/v1/auth/password", json={"current": PW, "new": NEW})
        return self.login(login, NEW), r.json()["id"]

    def set_site(self, sid, site_id):
        from vyonix.clinical.models import Study
        with _prep.db.session(self.t) as s:
            s.get(Study, uuid.UUID(sid)).site_id = uuid.UUID(site_id) if site_id else None

    # ------------------------------------------------------------------ R-01 / R-02 / R-03
    def test_r01_only_responsible_physician_writes_signs_and_adds(self):
        sid, _u = self.ready()
        ana, bruno = self.docs["ana"][0], self.docs["bruno"][0]
        rid = ana.post("/api/v1/report/reports", json={"study_id": sid}).json()["id"]
        r = ana.put(f"/api/v1/report/reports/{rid}", json={"body": "Texto sintético da Ana.",
                                                         "row_version": self.rv(ana, rid)})
        self.assertEqual(r.status_code, 200, r.text)
        rv = self.rv(ana, rid)
        base = f"/api/v1/report/reports/{rid}"
        self.assertEqual(bruno.get(base).status_code, 403)                       # rascunho alheio
        self.assertEqual(bruno.get(base + "/revisions").status_code, 403)
        self.assertEqual(bruno.get(base + "/draft-pdf").status_code, 403)
        self.assertEqual(bruno.put(base, json={"body": "ALTERADO", "row_version": rv}).status_code, 403)
        self.assertEqual(bruno.post(base + "/review", json={"row_version": rv}).status_code, 403)
        self.assertEqual(bruno.post(base + "/finalize", json={"password": NEW, "row_version": rv}).status_code, 403)
        out = bruno.post("/api/v1/report/reports/finalize-batch",
                         json={"report_ids": [rid], "password": NEW, "confirm": True}).json()
        self.assertEqual((out["released"], out["results"][0]["code"]), (0, "not_responsible"))
        self.assertEqual(ana.get(base).json()["body"], "Texto sintético da Ana.")   # nada mudou
        # a responsável libera; o adendo de outro médico continua recusado
        r = ana.post(base + "/finalize", json={"password": NEW, "row_version": rv})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(bruno.post(base + "/addenda", json={"text": "Adendo indevido", "password": NEW}).status_code,
                         403)
        self.assertEqual(ana.post(base + "/addenda", json={"text": "Adendo da autora", "password": NEW}).status_code,
                         201)
        self.assertEqual(bruno.get(base).status_code, 200)       # laudo liberado: leitura pelo escopo de unidade

    def test_r02_cannot_start_report_assigned_to_other(self):
        from sqlalchemy import select
        from vyonix.report.models import ReportStart
        sid, _u = self.ready()
        bruno = self.docs["bruno"][0]
        r = bruno.post("/api/v1/report/reports", json={"study_id": sid})
        self.assertEqual((r.status_code, r.json()["error"]), (409, "assigned_to_other"))
        with _prep.db.session(self.t) as s:
            self.assertIsNone(s.execute(select(ReportStart).where(ReportStart.study_id == uuid.UUID(sid)))
                              .scalar_one_or_none())
        r = self.docs["ana"][0].post("/api/v1/report/reports", json={"study_id": sid})
        self.assertEqual(r.status_code, 201, r.text)

    def test_r03_cannot_return_other_physicians_exam(self):
        sid, u = self.ready()
        bruno, ana = self.docs["bruno"][0], self.docs["ana"][0]
        before = self.tec.get(u).json()["physician"]
        self.assertTrue(before)
        r = bruno.post(u + "/return", json={"reason": "correção sintética"})
        self.assertEqual((r.status_code, r.json()["error"]), (403, "not_responsible"))
        self.assertEqual(self.tec.get(u).json()["physician"], before)            # atribuição preservada
        self.assertEqual(ana.post(u + "/return", json={"reason": "correção sintética"}).status_code, 200)

    # ------------------------------------------------------------------ R-04
    def test_r04_technician_limited_to_own_unit(self):
        a, b = self.site("Unidade A Sintética"), self.site("Unidade B Sintética")
        tec_a, _ = self.site_user("tec_a", "tecnico", a)
        sid = self.study(1)
        self.set_site(sid, b)
        u = f"/api/v1/ris/prep/{sid}"
        self.assertEqual(tec_a.get(u).status_code, 403)
        self.assertEqual(tec_a.get(f"/api/v1/ris/studies/{sid}/timeline").status_code, 403)
        self.assertEqual(tec_a.post(u + "/check", json={"code": "procedure"}).status_code, 403)
        self.assertEqual(tec_a.post(u + "/attachments?kind=document&filename=x.pdf", content=_prep.pdf()).status_code,
                         403)
        self.assertEqual(tec_a.post(u + "/forward").status_code, 403)
        self.assertEqual(tec_a.post(u + "/priority", json={"priority": "stat", "reason": "teste"}).status_code, 403)
        self.assertNotIn(sid, [x["study_id"] for x in tec_a.get("/api/v1/ris/prep").json()["items"]])
        # exame sem unidade: papel restrito a uma unidade não basta
        sid2 = self.study(2)
        self.set_site(sid2, None)
        r = tec_a.post(f"/api/v1/ris/prep/{sid2}/priority", json={"priority": "stat", "reason": "teste"})
        self.assertEqual(r.status_code, 403)
        # na própria unidade continua funcionando
        sid3 = self.study(3)
        self.set_site(sid3, a)
        self.assertEqual(tec_a.post(f"/api/v1/ris/prep/{sid3}/check", json={"code": "procedure"}).status_code, 200)

    # ------------------------------------------------------------------ R-05 / R-07
    def test_r05_reconcile_does_not_change_priority_after_start(self):
        from vyonix.clinical import service as clinical
        sid, u = self.ready()
        ana = self.docs["ana"][0]
        self.assertEqual(ana.post("/api/v1/report/reports", json={"study_id": sid}).status_code, 201)
        before = self.tec.get(u).json()["priority"]
        with _prep.db.session(self.t) as s:
            oid = str(clinical.create_order(s, patient_id=self.pat, priority="stat", actor="recepcao").id)
        self.assertEqual(self.tec.post(f"/api/v1/studies/{sid}/reconcile", json={"order_id": oid}).status_code, 200)
        self.assertEqual(self.tec.get(u).json()["priority"], before)

    def test_r07_row_version_required(self):
        sid, _u = self.ready()
        ana = self.docs["ana"][0]
        rid = ana.post("/api/v1/report/reports", json={"study_id": sid}).json()["id"]
        self.assertEqual(ana.put(f"/api/v1/report/reports/{rid}", json={"body": "sem versão"}).status_code, 422)
        self.assertEqual(ana.post(f"/api/v1/report/reports/{rid}/finalize", json={"password": NEW}).status_code, 422)
        rv = self.rv(ana, rid)
        self.assertEqual(ana.put(f"/api/v1/report/reports/{rid}", json={"body": "v1", "row_version": rv}).status_code,
                         200)
        self.assertEqual(ana.put(f"/api/v1/report/reports/{rid}", json={"body": "velha", "row_version": rv}).status_code,
                         409)

    # ------------------------------------------------------------------ S-01 / S-02
    def test_s01_site_admin_cannot_escalate(self):
        b = self.site("Filial B Sintética")
        gb, gb_id = self.site_user("gerente_b", "administrador", b)
        r = gb.put(f"/api/v1/users/{gb_id}/roles", json={"roles": [{"role": "administrador", "site_id": None}]})
        self.assertEqual((r.status_code, r.json()["error"]), (403, "self_roles"))
        admin_id = next(x["id"] for x in self.admin.get("/api/v1/users").json() if x["username"] == "admin")
        r = gb.post(f"/api/v1/users/{admin_id}/reset-password", json={"password": "Outra-Senha-12345"})
        self.assertEqual((r.status_code, r.json()["error"]), (403, "cannot_delegate"))
        r = gb.post("/api/v1/users", json={"username": "novo_global", "display_name": "x", "password": PW,
                                            "roles": [{"role": "tecnico", "site_id": None}]})
        self.assertEqual((r.status_code, r.json()["error"]), (403, "cannot_delegate"))
        r = gb.post("/api/v1/users", json={"username": "novo_b", "display_name": "x", "password": PW,
                                            "roles": [{"role": "tecnico", "site_id": b}]})
        self.assertEqual(r.status_code, 201, r.text)                 # na própria unidade, pode
        roles = [x for x in self.admin.get("/api/v1/users").json() if x["username"] == "gerente_b"][0]
        self.assertNotIn(None, [x.get("site_id") for x in roles.get("roles", [])])

    def test_s02_site_role_does_not_reach_institution(self):
        a, b = self.site("Unidade A Sintética"), self.site("Unidade B Sintética")
        tec_a, _ = self.site_user("tec_a2", "tecnico", a)
        ga, _ = self.site_user("gerente_a", "administrador", a)
        sid = self.study(1)
        self.set_site(sid, b)
        self.assertNotIn(sid, [x["id"] for x in tec_a.get("/api/v1/studies").json()])
        self.assertIn(sid, [x["id"] for x in self.admin.get("/api/v1/studies").json()])
        self.assertEqual(ga.get("/api/v1/audit").status_code, 403)
        r = ga.put("/api/v1/settings/core/security", json={"value": {}, "reason": "teste sintético"})
        self.assertEqual(r.status_code, 403)

    # ------------------------------------------------------------------ S-04
    def test_s04_logout_revokes_viewer_credentials(self):
        from datetime import timedelta
        from sqlalchemy import select
        from vyonix.db.base import utcnow
        from vyonix.pacs.models import ViewerToken
        ana, _pid, uid = self.docs["ana"]
        with _prep.db.session(self.t) as s:
            s.add(ViewerToken(user_id=uuid.UUID(uid), token_hash="0" * 64, kind="access", viewer="weasis",
                              study_uid="2.25.1", expires_at=utcnow() + timedelta(hours=1)))
        self.assertEqual(ana.post("/api/v1/auth/logout").status_code, 200)
        with _prep.db.session(self.t) as s:
            left = s.execute(select(ViewerToken).where(ViewerToken.user_id == uuid.UUID(uid),
                                                       ViewerToken.revoked_at.is_(None))).scalars().all()
        self.assertEqual(left, [])

    # ------------------------------------------------------------------ B-04
    def test_b04_app_role_cannot_rewrite_migration_version(self):
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError
        with self.assertRaises(DBAPIError) as cm:
            with _prep.db.session(self.t) as s:
                s.execute(text("UPDATE platform.alembic_version SET version_num = version_num"))
        self.assertIn("permission denied", str(cm.exception).lower())


if __name__ == "__main__":
    import unittest
    unittest.main()
