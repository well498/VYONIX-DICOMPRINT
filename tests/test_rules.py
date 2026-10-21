"""Fase 6 — motor de regras: avaliação, precedência, simulação, cadastro e integração com a fila."""

import unittest
from datetime import datetime

from app.core.errors import SettingsValidationError
from app.rules.engine import Rule, check_condition, evaluate
from tests.helpers import TempDirTestCase

try:
    import pynetdicom  # noqa: F401
    import numpy  # noqa: F401
    HAS = True
except ImportError:
    HAS = False


def R(rid, name, conds, actions, priority=100, active=True):
    return Rule(id=rid, name=name, conditions=conds, actions=actions, priority=priority, active=active)


class EvaluateTest(unittest.TestCase):
    facts = {"modality": "CT", "calling_ae": "CT_SALA2", "time": "22:30", "weekday": 6, "image_count": 12,
             "source": "storage", "study_description": "TC CRANIO"}

    def test_conditions(self):
        f = self.facts
        self.assertTrue(check_condition({"field": "modality", "op": "eq", "value": "ct"}, f)[0])
        self.assertTrue(check_condition({"field": "modality", "op": "in", "value": "MR, CT"}, f)[0])
        self.assertTrue(check_condition({"field": "calling_ae", "op": "startswith", "value": "CT_"}, f)[0])
        self.assertTrue(check_condition({"field": "study_description", "op": "contains", "value": "crânio"[:4]}, f)[0])
        self.assertTrue(check_condition({"field": "time", "op": "between", "value": "19:00-07:00"}, f)[0])  # noite
        self.assertFalse(check_condition({"field": "time", "op": "between", "value": "08:00-18:00"}, f)[0])
        self.assertTrue(check_condition({"field": "weekday", "op": "in", "value": "6,7"}, f)[0])
        self.assertTrue(check_condition({"field": "image_count", "op": "gte", "value": "10"}, f)[0])
        ok, why = check_condition({"field": "body_part", "op": "eq", "value": "HEAD"}, f)
        self.assertFalse(ok)
        self.assertIn("sem valor", why)

    def test_priority_and_stop(self):
        rules = [
            R(1, "Geral", [], {"copies": 1, "paper": "A4", "footer_text": "geral"}, priority=200),
            R(2, "CT noite", [{"field": "modality", "op": "eq", "value": "CT"},
                              {"field": "time", "op": "between", "value": "19:00-07:00"}],
              {"copies": 2, "hold": True, "priority": 20}, priority=10),
            R(3, "MR", [{"field": "modality", "op": "eq", "value": "MR"}], {"layout": "3x3"}, priority=5),
            R(4, "Inativa", [], {"copies": 9}, priority=1, active=False),
        ]
        ev = evaluate(rules, self.facts)
        self.assertEqual(ev.values["copies"], 2)                  # maior prioridade vence
        self.assertEqual(ev.values["paper"], "A4")                # regra seguinte completa
        self.assertEqual(ev.origins["copies"], "Regra “CT noite”")
        self.assertEqual((ev.hold, ev.priority), ("CT noite", 20))
        self.assertEqual(ev.matched, ["CT noite", "Geral"])
        self.assertTrue(any(line.startswith("✗ Regra “MR”") for line in ev.explanation))
        rules[1].actions["stop"] = True
        ev = evaluate(rules, self.facts)
        self.assertNotIn("paper", ev.values)
        self.assertTrue(any("encerra" in line for line in ev.explanation))

    def test_no_rule(self):
        ev = evaluate([], self.facts)
        self.assertEqual(ev.values, {})
        self.assertIn("Nenhuma regra", ev.explanation[-1])


class RuleServiceTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        from app.bootstrap import bootstrap
        self.ctx = bootstrap(data_dir=self.tmp / "data")

    def tearDown(self):
        self.ctx.close()
        super().tearDown()

    def test_validation(self):
        bad = [
            R(None, "", [], {"copies": 1}),
            R(None, "x", [{"field": "nada", "op": "eq", "value": 1}], {"copies": 1}),
            R(None, "x", [{"field": "image_count", "op": "contains", "value": "1"}], {"copies": 1}),
            R(None, "x", [{"field": "time", "op": "between", "value": "25:00-26:00"}], {"copies": 1}),
            R(None, "x", [], {}),
            R(None, "x", [], {"copies": 0}),
            R(None, "x", [], {"paper": "A9"}),
            R(None, "x", [], {"layout": "9x9"}),
            R(None, "x", [], {"profile_id": 999}),
        ]
        for r in bad:
            with self.assertRaises(SettingsValidationError, msg=repr(r)):
                self.ctx.rules.save(r, actor="t")

    def test_crud_history_move_export_import(self):
        a = self.ctx.rules.save(R(None, "A", [], {"copies": 2}, priority=10), actor="t")
        b = self.ctx.rules.save(R(None, "B", [{"field": "modality", "op": "eq", "value": "CR"}],
                                  {"paper": "A3"}, priority=20), actor="t")
        with self.assertRaises(SettingsValidationError):
            self.ctx.rules.save(R(None, "A", [], {"copies": 1}), actor="t")
        self.ctx.rules.move(b.id, -1, actor="t")
        self.assertEqual([r.name for r in self.ctx.rules.list()], ["B", "A"])
        self.ctx.rules.set_active(a.id, False, actor="t")
        self.assertEqual([r.name for r in self.ctx.rules.list(include_inactive=False)], ["B"])
        data = self.ctx.rules.export_json()
        self.ctx.rules.delete(a.id, actor="t")
        self.assertEqual(self.ctx.rules.import_json(data, actor="t"), 2)
        self.assertEqual(sorted(r.name for r in self.ctx.rules.list()), ["A", "B"])
        hist = self.ctx.changes.list(entity_type="rule")
        self.assertGreaterEqual(len(hist), 5)


@unittest.skipUnless(HAS, "pynetdicom/numpy não instalados")
class RulesInQueueTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        from app.bootstrap import bootstrap
        from app.printing.backends.pdf import PDF_PRINTER
        self.ctx = bootstrap(data_dir=self.tmp / "data")
        self.ctx.printers.refresh()
        self.ctx.settings.update({"printing.default_printer": PDF_PRINTER, "printing.dpi": 150}, actor="t")
        self.dev = self.ctx.devices.create({"name": "CT 2", "ae_title": "CT_SALA2", "modality": "CT",
                                            "site": "Unidade Centro", "ip_address": "127.0.0.1"},
                                           actor="t", authorized=True)

    def tearDown(self):
        self.ctx.close()
        super().tearDown()

    def receive(self, n=1):
        from app.dicom import scu
        from tests.dicom_helpers import free_port, make_ct
        port = free_port()
        self.ctx.settings.update({"dicom.storage.bind_address": "127.0.0.1", "dicom.storage.port": port}, actor="t")
        self.ctx.storage_scp.start()
        files = [make_ct(self.tmp / f"in/{i}.dcm") for i in range(n)]
        self.assertEqual(scu.store_files("127.0.0.1", port, "VYONIX", files, calling_ae="CT_SALA2"), [0] * n)
        self.ctx.worker.collector.flush(force=True)
        return self.ctx.jobs.list()[0]

    def test_precedence_rule_over_profile_and_hold(self):
        from app.jobs.states import JobState
        from app.printing.profiles import PrintProfile
        p = self.ctx.profiles.save(PrintProfile(id=None, name="CT perfil", layout="2x2", copies=3, paper_size="A3"),
                                   actor="t")
        self.ctx.profiles.bind(p.id, "modality", "CT", actor="t")
        self.ctx.rules.save(R(None, "Centro", [{"field": "site", "op": "eq", "value": "unidade centro"},
                                               {"field": "image_count", "op": "gte", "value": "2"}],
                              {"copies": 1, "hold": True, "priority": 50}), actor="t")
        job = self.receive(2)
        self.assertEqual(job.state, JobState.HELD)
        self.assertIn("Centro", job.state_reason)
        self.assertEqual(job.priority, 50)
        self.assertEqual((job.copies, job.settings["layout"], job.settings["paper"]), (1, "2x2", "A3"))
        self.assertEqual(job.origins["copies"], "Regra “Centro”")
        self.assertIn("CT perfil", job.origins["layout"])
        self.assertIn("✓ Regra", job.origins["_rules"])
        rid = self.ctx.db.connection().execute("SELECT rule_id FROM jobs WHERE id=?", (job.id,)).fetchone()[0]
        self.assertIsNotNone(rid)

    def test_rule_applies_profile_and_reprocess_uses_current_rules(self):
        from app.printing.profiles import PrintProfile
        p = self.ctx.profiles.save(PrintProfile(id=None, name="Laudo", layout="1x2"), actor="t")
        job = self.receive(1)
        self.assertEqual(job.settings["layout"], "1x1")
        self.ctx.jobs.hold(job.id, actor="t")
        self.ctx.rules.save(R(None, "Usa laudo", [{"field": "calling_ae", "op": "eq", "value": "CT_SALA2"}],
                              {"profile_id": p.id, "footer_text": "Revisado"}), actor="t")
        self.ctx.jobs.reprocess(job.id, actor="t")
        job = self.ctx.jobs.get_job(job.id)
        self.assertEqual((job.settings["layout"], job.settings["footer_text"]), ("1x2", "Revisado"))
        self.assertIn("regra “Usa laudo”", job.origins["layout"])
