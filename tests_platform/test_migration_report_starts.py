"""A08 (04/11/2026): o preenchimento da report_0012 grava o médico responsável dos laudos antigos (atribuição mais
recente; sem atribuição, o médico do usuário autor), para a devolução para correção voltar ao mesmo médico."""
from __future__ import annotations

import importlib.util
import unittest
import uuid
from datetime import date
from pathlib import Path

import tests_platform.test_report_sla_distribution as _sla


def setUpModule():
    _sla.setUpModule()


def _backfill_sql() -> str:
    p = Path(__file__).resolve().parents[1] / "vyonix/db/migrations/versions/report_0012_bloqueio_inicio_laudo.py"
    spec = importlib.util.spec_from_file_location("m0012", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.BACKFILL_SQL


class Backfill(_sla.SlaAndDistribution):
    locals().update({n: None for n in dir(_sla.SlaAndDistribution) if n.startswith("test_")})

    def test_backfill_keeps_responsible_physician(self):
        from sqlalchemy import create_engine, select, text
        from tests_platform.support import urls
        from vyonix.report.models import ReportStart
        sid_a, u_a = self.ready(1)
        sid_b, u_b = self.ready(2)
        ana, pid_ana, _ = self.docs["ana"]
        bruno, pid_bruno, _ = self.docs["bruno"]
        self.tec.post(u_a + "/physician", json={"physician_id": pid_ana, "reason": "escala"})
        ana.post("/api/v1/report/reports", json={"study_id": sid_a})              # com atribuição
        self.assertIn(bruno.post("/api/v1/report/reports", json={"study_id": sid_b}).status_code, (200, 201))
        eng = create_engine(urls().owner)                                        # simula a base anterior à 0012
        with eng.begin() as cx:
            cx.execute(text("DELETE FROM report.report_starts"))
            cx.execute(text(_backfill_sql()))
        eng.dispose()
        with _sla._prep.db.session(self.t) as s:
            rows = {str(r.study_id): r for r in s.execute(select(ReportStart)).scalars()}
        self.assertEqual(rows[sid_a].origin, "migracao")
        self.assertEqual(str(rows[sid_a].physician_id), pid_ana)                 # da atribuição
        self.assertEqual(str(rows[sid_b].physician_id), pid_bruno)               # do usuário autor do laudo
        self.assertEqual(rows[sid_b].physician_name, "Dr. Bruno Sintetico")


if __name__ == "__main__":
    unittest.main()
