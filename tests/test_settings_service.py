"""F1-06 — configurações tipadas, validadas, auditadas, exportáveis."""

import json

from app.core.errors import SettingsValidationError
from app.database.repositories.events_repo import Category, EventFilter
from app.security import validators as v
from app.core.errors import ValidationError
from app.services.settings_service import SettingsService
from tests.helpers import DatabaseTestCase


class ValidatorsTest(DatabaseTestCase):
    def test_ae_title(self):
        self.assertEqual(v.validate_ae_title("  CT_SALA1 "), "CT_SALA1")
        for bad in ("", "    ", "A" * 17, "BAD\\AE", "ÇT", "TAB\tX", 123):
            with self.assertRaises(ValidationError, msg=repr(bad)):
                v.validate_ae_title(bad)

    def test_port_and_ip(self):
        self.assertEqual(v.validate_port("104"), 104)
        for bad in (0, 70000, "abc", True, 1.5):
            with self.assertRaises(ValidationError):
                v.validate_port(bad)
        self.assertEqual(v.validate_bind_address(" 192.168.0.10 "), "192.168.0.10")
        with self.assertRaises(ValidationError):
            v.validate_bind_address("300.1.1.1")
        self.assertTrue(v.port_warnings(104))
        self.assertFalse(v.port_warnings(11112))


class SettingsServiceTest(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.svc = SettingsService(self.db, self.events)
        self.svc.ensure_defaults()

    def test_defaults_and_installation_id(self):
        values = self.svc.get_all()
        self.assertEqual(values["dicom.storage.ae_title"], "VYONIX")
        self.assertEqual(values["dicom.storage.port"], 11112)
        self.assertFalse(values["dicom.storage.accept_unknown"])
        iid = values["system.installation_id"]
        self.assertEqual(len(iid), 36)
        self.svc.ensure_defaults()
        self.assertEqual(self.svc.get("system.installation_id"), iid)

    def test_update_is_persisted_audited_and_notified(self):
        seen = []
        self.svc.subscribe(seen.append)
        result = self.svc.update({"dicom.storage.ae_title": " CLINICA ", "dicom.storage.port": 104},
                                 actor="ui:ana", reason="implantação")
        self.assertEqual(self.svc.get("dicom.storage.ae_title"), "CLINICA")
        self.assertTrue(result.restart_required)
        self.assertTrue(result.warnings)
        self.assertEqual(seen, [{"dicom.storage.ae_title": "CLINICA", "dicom.storage.port": 104}])
        hist = self.svc.history.list(entity_type="settings")
        self.assertEqual({h.entity_id for h in hist}, {"dicom.storage.ae_title", "dicom.storage.port"})
        self.assertEqual(hist[0].changed_by, "ui:ana")
        ev = self.events.query(EventFilter(categories=(Category.ADMIN,)))
        self.assertEqual(ev[0].action, "settings.update")

    def test_invalid_update_writes_nothing(self):
        with self.assertRaises(SettingsValidationError) as cm:
            self.svc.update({"dicom.storage.port": 70000, "site.name": "Unidade Centro"},
                            actor="t")
        self.assertIn("dicom.storage.port", cm.exception.errors)
        self.assertEqual(self.svc.get("site.name"), "")

    def test_unknown_and_readonly_keys_rejected(self):
        with self.assertRaises(SettingsValidationError) as cm:
            self.svc.update({"nao.existe": 1, "system.installation_id": "X"}, actor="t")
        self.assertEqual(set(cm.exception.errors), {"nao.existe", "system.installation_id"})

    def test_cross_field_rules(self):
        with self.assertRaises(SettingsValidationError) as cm:
            self.svc.update({"dicom.print.enabled": True, "dicom.print.port": 11112,
                             "dicom.print.ae_title": "VYONIX"}, actor="t")
        self.assertEqual(set(cm.exception.errors), {"dicom.print.port", "dicom.print.ae_title"})

    def test_unchanged_values_produce_no_history(self):
        result = self.svc.update({"dicom.storage.ae_title": "VYONIX"}, actor="t")
        self.assertFalse(result.changed)
        self.assertEqual(self.svc.history.list(), [])

    def test_tampered_stored_value_falls_back_to_default(self):
        self.svc.repo.upsert("dicom.storage.port", "não é porta", "manual")
        self.assertEqual(self.svc.get("dicom.storage.port"), 11112)
        self.assertEqual(self.svc.get_all()["dicom.storage.port"], 11112)

    def test_export_import_roundtrip(self):
        self.svc.update({"site.name": "Hospital X", "jobs.max_attempts": 5}, actor="t")
        path = self.svc.export_json(self.tmp / "cfg.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertNotIn("system.installation_id", data["settings"])
        self.svc.reset_to_defaults(actor="t")
        self.assertEqual(self.svc.get("site.name"), "")
        self.svc.import_json(path, actor="t")
        self.assertEqual(self.svc.get("site.name"), "Hospital X")
        self.assertEqual(self.svc.get("jobs.max_attempts"), 5)

    def test_import_rejects_foreign_files(self):
        bad = self.tmp / "x.json"
        bad.write_text('{"format": "outro"}', encoding="utf-8")
        with self.assertRaises(SettingsValidationError):
            self.svc.import_json(bad, actor="t")
        bad.write_text("{quebrado", encoding="utf-8")
        with self.assertRaises(SettingsValidationError):
            self.svc.import_json(bad, actor="t")

    def test_failing_listener_does_not_break_update(self):
        self.svc.subscribe(lambda _: 1 / 0)
        self.svc.update({"site.name": "A"}, actor="t")
        self.assertEqual(self.svc.get("site.name"), "A")
