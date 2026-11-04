"""Regras do proprietário de 04/11/2026 (PostgreSQL real, dados sintéticos):

1. Trocar médico e alterar prioridade são EXCLUSIVOS do Técnico em Radiologia (papel ``tecnico`` na unidade do exame);
   administrador, coordenação, médico e acumulação de outros papéis não concedem; justificativa obrigatória;
   auditoria com usuário, horário, valor anterior e novo.
2. Ao iniciar efetivamente o laudo (o médico abre o rascunho), ambas ficam bloqueadas para todos — inclusive o
   técnico —, em todas as rotas (prioridade, troca, pedidos, reserva e desistência), e o bloqueio persiste em
   rascunho, revisão e laudo assinado; abrir imagens/consultar não bloqueia; o aplicativo não consegue apagar o
   registro de início; operações simultâneas não passam do início do laudo.
"""
from __future__ import annotations

import threading
import unittest
import uuid

import tests_platform.test_ris_prep as _prep

LOCK = "Alteração indisponível: laudo já iniciado"


def setUpModule():
    _prep.setUpModule()


class ExclusiveAndLock(_prep.Prep):
    # só os testes deste módulo (a classe base é importada como módulo para não repetir os dela)
    locals().update({n: None for n in dir(_prep.Prep) if n.startswith("test_")})

    def ready(self, n=1):
        sid = self.study(n)
        u = f"/api/v1/ris/prep/{sid}"
        for code in ("patient_identity", "procedure", "quality"):
            self.tec.post(u + "/check", json={"code": code})
        self.assertEqual(self.tec.post(u + "/forward").status_code, 200)
        return sid, u

    def audit(self, action, sid):
        from sqlalchemy import select
        from vyonix.audit.models import AuditEntry
        with _prep.db.session(self.t) as s:
            return [e.details for e in s.execute(select(AuditEntry).where(
                AuditEntry.action == action, AuditEntry.target_id == str(sid)).order_by(AuditEntry.seq)).scalars()]

    def test_only_technician_changes_and_everything_is_audited(self):
        sid, u = self.ready()
        _, pid_ana, _ = self.docs["ana"]
        _, pid_bruno, _ = self.docs["bruno"]
        ana = self.docs["ana"][0]
        # quem não é técnico: recusado no backend, mesmo com permissões amplas
        for who in (self.admin, self.coord, ana):
            r = who.post(u + "/priority", json={"priority": "stat", "reason": "teste"})
            self.assertEqual((r.status_code, r.json()["error"]), (403, "technician_only"))
            r = who.post(u + "/physician", json={"physician_id": pid_ana, "reason": "teste"})
            self.assertEqual((r.status_code, r.json()["error"]), (403, "technician_only"))
            r = who.post("/api/v1/report/assignments", json={"study_id": sid, "physician_id": pid_ana, "reason": "teste"})
            self.assertEqual((r.status_code, r.json()["error"]), (403, "technician_only"))
        # acumulação de papéis sem o papel de técnico não concede
        acc = self.user("acumula", ["administrador", "coordenador_cdi", "medico"])
        self.assertEqual(acc.post(u + "/priority", json={"priority": "stat", "reason": "teste"}).status_code, 403)
        # técnico: justificativa obrigatória
        self.assertEqual(self.tec.post(u + "/priority", json={"priority": "stat"}).status_code, 422)
        self.assertEqual(self.tec.post(u + "/physician", json={"physician_id": pid_ana}).status_code, 422)
        self.assertEqual(self.tec.post(u + "/priority", json={"priority": "stat", "reason": "dor intensa"}).status_code,
                         200)
        names = {x["name"] for x in self.tec.get(u + "/eligible-physicians").json()["items"]}
        self.assertEqual(names, {"Dra. Ana Sintetica", "Dr. Bruno Sintetico"})
        self.assertEqual(self.tec.post(u + "/physician", json={"physician_id": pid_ana, "reason": "escala"}).status_code,
                         200)
        self.assertEqual(self.tec.post(u + "/physician", json={"physician_id": pid_bruno, "reason": "plantão"})
                         .status_code, 200)
        pr = self.audit("ris.prep.priority", sid)
        self.assertEqual((pr[-1]["from"], pr[-1]["to"], pr[-1]["reason"]), ("routine", "stat", "dor intensa"))
        asg = self.audit("report.assign", sid)
        self.assertEqual((asg[-1]["previous"]["physician"], asg[-1]["physician"], asg[-1]["reason"]),
                         ("Dra. Ana Sintetica", "Dr. Bruno Sintetico", "plantão"))
        d = self.tec.get(u).json()
        self.assertEqual((d["can"]["priority"], d["can"]["change_physician"], d["changes_locked"]), (True, True, False))
        d = self.coord.get(u).json()                       # outros perfis só visualizam
        self.assertEqual((d["can"]["priority"], d["can"]["change_physician"], d["can"]["assign"]), (False, False, False))
        self.assertEqual(d["physician"], "Dr. Bruno Sintetico")

    def test_technician_of_another_unit_cannot(self):
        from vyonix.tenancy.models import Site
        sid, u = self.ready()
        with _prep.db.session(self.t) as s:
            other = Site(name="Unidade Outra Sintetica")
            s.add(other)
            s.flush()
            other_id = str(other.id)
        r = self.admin.post("/api/v1/users", json={"username": "tec_outra", "display_name": "tec_outra",
                                                   "password": _prep.PW, "roles": [{"role": "tecnico",
                                                                                    "site_id": other_id}]})
        self.assertEqual(r.status_code, 201, r.text)
        c = self.login("tec_outra", _prep.PW)
        c.post("/api/v1/auth/password", json={"current": _prep.PW, "new": _prep.NEW})
        c = self.login("tec_outra", _prep.NEW)
        with _prep.db.session(self.t) as s:              # o exame passa a ser de uma unidade diferente
            from vyonix.clinical.models import Study
            site = Site(name="Unidade do Exame Sintetica")
            s.add(site)
            s.flush()
            s.get(Study, uuid.UUID(sid)).site_id = site.id
        self.assertEqual(c.post(u + "/priority", json={"priority": "stat", "reason": "teste"}).status_code, 403)

    def test_report_start_locks_everything_permanently(self):
        sid, u = self.ready()
        ana, pid_ana, _ = self.docs["ana"]
        _, pid_bruno, _ = self.docs["bruno"]
        self.assertEqual(self.tec.post(u + "/physician", json={"physician_id": pid_ana, "reason": "escala"}).status_code,
                         200)
        # consultar e abrir imagens não inicia o bloqueio
        ana.get(u)
        ana.get(f"/api/v1/ris/studies/{sid}/timeline")
        self.assertFalse(self.tec.get(u).json()["changes_locked"])
        # o médico inicia o laudo
        r = ana.post("/api/v1/report/reports", json={"study_id": sid})
        self.assertIn(r.status_code, (200, 201), r.text)
        rid = r.json()["id"]
        d = self.tec.get(u).json()
        self.assertTrue(d["changes_locked"])
        self.assertTrue(d["report_started_at"])
        self.assertEqual((d["lock_message"], d["can"]["priority"], d["can"]["change_physician"]), (LOCK, False, False))
        self.assertEqual(d["physician"], "Dra. Ana Sintetica")
        item = next(x for x in self.tec.get("/api/v1/ris/prep").json()["items"] if x["study_id"] == sid)
        self.assertTrue(item["changes_locked"] and item["report_started_at"])

        def refused(r):
            self.assertEqual((r.status_code, r.json()["error"], r.json()["message"]), (409, "report_started", LOCK),
                             r.text)
        refused(self.tec.post(u + "/priority", json={"priority": "stat", "reason": "urgência"}))
        refused(self.tec.post(u + "/physician", json={"physician_id": pid_bruno, "reason": "plantão"}))
        refused(self.tec.post("/api/v1/report/assignments", json={"study_id": sid, "physician_id": pid_bruno,
                                                                   "reason": "plantão"}))
        refused(self.tec.post(u + "/flags", json={"code": "doctor_change", "note": "pedido"}))
        refused(self.tec.post(u + "/flags", json={"code": "priority_request", "note": "pedido"}))
        bruno = self.docs["bruno"][0]
        self.assertEqual(bruno.post(f"/api/v1/report/queue/{sid}/claim").status_code, 409)
        # o bloqueio continua após salvar, liberar (assinar) o laudo
        rv = ana.put(f"/api/v1/report/reports/{rid}", json={"body": "Texto sintético."}).json()["row_version"]
        r = ana.post(f"/api/v1/report/reports/{rid}/finalize", json={"password": _prep.NEW, "row_version": rv})
        self.assertEqual(r.status_code, 200, r.text)
        refused(self.tec.post(u + "/priority", json={"priority": "stat", "reason": "urgência"}))
        refused(self.tec.post(u + "/physician", json={"physician_id": pid_bruno, "reason": "plantão"}))
        started = self.audit("report.started", sid)
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0]["locks"], ["trocar_medico", "prioridade"])

    def test_application_role_cannot_remove_the_start_record(self):
        sid, u = self.ready()
        ana = self.docs["ana"][0]
        ana.post("/api/v1/report/reports", json={"study_id": sid})
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError
        with self.assertRaises(DBAPIError):
            with _prep.db.session(self.t) as s:          # sessão do aplicativo (papel sem UPDATE/DELETE)
                s.execute(text("DELETE FROM report.report_starts WHERE study_id = :s"), {"s": sid})
        with self.assertRaises(DBAPIError):
            with _prep.db.session(self.t) as s:
                s.execute(text("UPDATE report.report_starts SET started_by = 'x' WHERE study_id = :s"), {"s": sid})
        self.assertTrue(self.tec.get(u).json()["changes_locked"])

    def test_concurrent_change_cannot_pass_report_start(self):
        """Início do laudo e troca de prioridade simultâneos: a troca espera e é recusada."""
        from vyonix.errors import Conflict
        from vyonix.report import service as rep
        from vyonix.ris import prep
        sid, u = self.ready()
        study = uuid.UUID(sid)
        opened = threading.Event()
        release = threading.Event()
        result: dict = {}

        def start_report():
            with _prep.db.session(self.t) as s:
                rep.open_report(s, study, actor="dra_concorrente")
                opened.set()
                release.wait(10)                              # mantém a transação aberta

        def change_priority():
            opened.wait(10)
            try:
                with _prep.db.session(self.t) as s:
                    prep.set_priority(s, study, "stat", reason="corrida", actor="tec_concorrente")
                result["ok"] = True
            except Conflict as e:
                result["err"] = str(e)

        a = threading.Thread(target=start_report)
        b = threading.Thread(target=change_priority)
        a.start()
        b.start()
        b.join(1.5)
        self.assertTrue(b.is_alive(), "a alteração deveria esperar o início do laudo terminar")
        release.set()
        a.join(10)
        b.join(10)
        self.assertEqual(result, {"err": LOCK})
        self.assertNotEqual(self.tec.get(u).json()["priority"], "stat")


if __name__ == "__main__":
    unittest.main()
