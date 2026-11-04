"""Decisões do proprietário de 04/11/2026 03:21 (PostgreSQL real, dados sintéticos):

* prazos iniciais Rotina 48 h / Prioritário 4 h / Urgente 1 h, configuráveis por instituição com a permissão
  específica ``report.sla.manage``; a mudança não altera prazos em andamento, salvo regra explícita e auditada;
* primeira atribuição manual e troca: só o Técnico em Radiologia; distribuição automática continua;
* o médico assume exame livre (sem atribuição) e sem laudo iniciado; não assume exame de outro;
* atribuições simultâneas conflitantes não passam; tudo auditado.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime

import tests_platform.test_ris_prep as _prep


def setUpModule():
    _prep.setUpModule()


class SlaAndDistribution(_prep.Prep):
    locals().update({n: None for n in dir(_prep.Prep) if n.startswith("test_")})

    def ready(self, n=1):
        sid = self.study(n)
        u = f"/api/v1/ris/prep/{sid}"
        for code in ("patient_identity", "procedure", "quality"):
            self.tec.post(u + "/check", json={"code": code})
        self.tec.post(u + "/duplicate", json={})                 # outro exame do mesmo paciente: não é duplicado
        r = self.tec.post(u + "/forward")
        self.assertEqual(r.status_code, 200, r.text)
        return sid, u

    def hours_left(self, sid):
        from sqlalchemy import select
        from vyonix.report.models import Assignment
        with _prep.db.session(self.t) as s:
            a = s.execute(select(Assignment).where(Assignment.study_id == uuid.UUID(sid),
                                                   Assignment.status == "open")).scalar_one()
            return (a.due_at - datetime.now(a.due_at.tzinfo)).total_seconds() / 3600

    def test_sla_defaults_permission_and_no_retroactive_change(self):
        self.assertEqual(self.tec.get("/api/v1/report/sla").json()["hours"], {"routine": 48, "urgent": 4, "stat": 1})
        sid, u = self.ready(1)
        _, pid, _ = self.docs["ana"]
        self.tec.post(u + "/physician", json={"physician_id": pid, "reason": "escala"})
        self.assertAlmostEqual(self.hours_left(sid), 48, delta=0.1)
        new = {"routine": 24, "urgent": 3, "stat": 1, "reason": "contrato novo"}
        for who in (self.tec, self.coord, self.docs["ana"][0]):            # sem a permissão específica
            self.assertEqual(who.put("/api/v1/report/sla", json=new).status_code, 403)
        r = self.coord.put("/api/v1/settings/report/sla", json={"value": {"routine": 24, "urgent": 3, "stat": 1}})
        self.assertEqual(r.status_code, 403)                               # nem pela rota genérica
        bad = dict(new, stat=5)
        self.assertEqual(self.admin.put("/api/v1/report/sla", json=bad).status_code, 422)   # Urgente ≤ Prioritário
        self.assertEqual(self.admin.put("/api/v1/report/sla", json={k: v for k, v in new.items() if k != "reason"})
                         .status_code, 422)                                # justificativa obrigatória
        r = self.admin.put("/api/v1/report/sla", json=new)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["reapplied"], 0)
        self.assertAlmostEqual(self.hours_left(sid), 48, delta=0.1)        # exame em andamento: prazo mantido
        sid2, u2 = self.ready(2)
        self.tec.post(u2 + "/physician", json={"physician_id": pid, "reason": "escala"})
        self.assertAlmostEqual(self.hours_left(sid2), 24, delta=0.1)       # novo exame: prazo novo
        r = self.admin.put("/api/v1/report/sla", json=dict(new, routine=12, apply_to_open=True,
                                                           reason="regra aprovada pela direção"))
        self.assertEqual(r.json()["reapplied"], 2)                          # regra explícita
        self.assertAlmostEqual(self.hours_left(sid), 12, delta=0.1)
        from sqlalchemy import select
        from vyonix.audit.models import AuditEntry
        with _prep.db.session(self.t) as s:
            ev = s.execute(select(AuditEntry).where(AuditEntry.action == "report.sla.reapplied")).scalars().all()
            self.assertEqual((len(ev), ev[0].details["count"], ev[0].details["reason"]),
                             (1, 2, "regra aprovada pela direção"))

    def test_claim_rules_and_restore_after_correction(self):
        sid, u = self.ready(1)
        ana, pid_ana, _ = self.docs["ana"]
        bruno = self.docs["bruno"][0]
        self.assertEqual(ana.post(f"/api/v1/report/queue/{sid}/claim").status_code, 200)   # livre e sem laudo
        r = bruno.post(f"/api/v1/report/queue/{sid}/claim")
        self.assertEqual((r.status_code, r.json()["error"]), (409, "already_assigned"))    # de outro: não
        self.assertEqual(ana.post("/api/v1/report/reports", json={"study_id": sid}).status_code in (200, 201), True)
        # devolvido para correção (atribuição encerrada) e reencaminhado: volta à mesma médica, ninguém assume
        self.assertEqual(ana.post(u + "/return", json={"reason": "Falta a série coronal"}).status_code, 200)
        r = bruno.post(f"/api/v1/report/queue/{sid}/claim")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.tec.post(u + "/forward").json()["assigned_to"], "Dra. Ana Sintetica")
        self.assertEqual(self.tec.get(u).json()["physician"], "Dra. Ana Sintetica")
        r = bruno.post(f"/api/v1/report/queue/{sid}/claim")
        self.assertEqual((r.status_code, r.json()["error"]), (409, "already_assigned"))

    def test_concurrent_conflicting_assignments(self):
        from vyonix.report import queue
        sid, _u = self.ready(1)
        pids = [uuid.UUID(self.docs["ana"][1]), uuid.UUID(self.docs["bruno"][1])]
        errors: list = []

        def go(pid):
            try:
                with _prep.db.session(self.t) as s:
                    queue.assign(s, uuid.UUID(sid), pid, priority="routine", reason="corrida", actor="tec")
            except Exception as e:                                          # noqa: BLE001
                errors.append(e)
        ts = [threading.Thread(target=go, args=(p,)) for p in pids]
        for t in ts:
            t.start()
        for t in ts:
            t.join(15)
        from sqlalchemy import select
        from vyonix.report.models import Assignment
        with _prep.db.session(self.t) as s:
            open_ = s.execute(select(Assignment).where(Assignment.study_id == uuid.UUID(sid),
                                                       Assignment.status == "open")).scalars().all()
        self.assertEqual(len(open_), 1, errors)                              # nunca dois responsáveis


if __name__ == "__main__":
    import unittest
    unittest.main()
