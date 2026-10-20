"""Fase 2 — cadastro de equipamentos e política de associação."""

from app.core.errors import SettingsValidationError, ValidationError
from app.devices.service import DeviceService
from app.dicom.association_manager import DIAG_CALLED_AE, DIAG_CALLING_AE, AssociationPolicy
from tests.helpers import DatabaseTestCase

CT = {"name": "Tomógrafo Sala 2", "ae_title": "CT_SALA2", "modality": "CT",
      "ip_address": "192.168.10.25", "port": "104", "manufacturer": "Fabricante X"}


class DeviceServiceTest(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.calls = []
        self.svc = DeviceService(self.db, self.events,
                                 echo=lambda d: self.calls.append(d) or {"ok": True, "status": 0,
                                                                         "ms": 5, "detail": "ok"})

    def test_create_validates_and_audits(self):
        d = self.svc.create(CT, actor="ui:ana")
        self.assertEqual((d.ae_title, d.port, d.authorized), ("CT_SALA2", 104, False))
        hist = self.svc.history.list(entity_type="device")
        self.assertEqual(hist[0].field, "created")
        self.assertEqual(self.svc.history_events(d.id)[0].action, "device.create")

    def test_invalid_fields(self):
        with self.assertRaises(SettingsValidationError) as cm:
            self.svc.create({"name": "", "ae_title": "MUITO_LONGO_AE_TITLE_X", "ip_address": "999.1.1.1",
                             "port": 0, "modality": "ZZ"}, actor="t")
        self.assertEqual(set(cm.exception.errors), {"name", "ae_title", "ip_address", "port", "modality"})

    def test_unique_ae_title(self):
        self.svc.create(CT, actor="t")
        with self.assertRaises(SettingsValidationError) as cm:
            self.svc.create({**CT, "name": "Outro"}, actor="t")
        self.assertIn("ae_title", cm.exception.errors)

    def test_update_records_each_field(self):
        d = self.svc.create(CT, actor="t")
        self.svc.update(d.id, {"site": "Unidade Centro", "port": 11112}, actor="t")
        fields = {h.field for h in self.svc.history.list(entity_type="device", entity_id=str(d.id))}
        self.assertTrue({"site", "port"} <= fields)
        self.assertEqual(self.svc.get(d.id).port, 11112)

    def test_authorize_block(self):
        d = self.svc.create(CT, actor="t")
        self.assertTrue(self.svc.set_authorized(d.id, True, actor="t").authorized)
        self.assertFalse(self.svc.set_authorized(d.id, False, actor="t").authorized)

    def test_remove_deletes_or_deactivates(self):
        a = self.svc.create(CT, actor="t")
        self.assertEqual(self.svc.remove(a.id, actor="t"), "deleted")
        b = self.svc.create(CT, actor="t")
        self.db.connection().execute(
            "INSERT INTO instances(sop_instance_uid, sop_class_uid, study_uid, series_uid, transfer_syntax,"
            " file_path, file_sha256, file_size, source_ae, device_id, received_at)"
            " VALUES ('1.2', '1.2', '1.2', '1.2', '1.2', 'x', 'h', 1, 'CT_SALA2', ?, 't')", (b.id,))
        self.assertEqual(self.svc.remove(b.id, actor="t"), "deactivated")
        self.assertFalse(self.svc.get(b.id).active)
        # O AE Title de um equipamento desativado pode ser reutilizado.
        self.svc.create(CT, actor="t")

    def test_echo_requires_address(self):
        d = self.svc.create({**CT, "ip_address": "", "port": ""}, actor="t")
        with self.assertRaises(ValidationError):
            self.svc.echo(d.id, actor="t")
        d = self.svc.update(d.id, {"ip_address": "127.0.0.1", "port": 104}, actor="t")
        self.assertTrue(self.svc.echo(d.id, actor="t")["ok"])
        self.assertEqual(self.svc.get(d.id).comm_status, "echo ok")

    def test_export_import(self):
        self.svc.set_authorized(self.svc.create(CT, actor="t").id, True, actor="t")
        path = self.tmp / "eq.json"
        self.assertEqual(self.svc.export_json(path), 1)
        other = DeviceService(self.db, self.events)
        result = other.import_json(path, actor="t")
        self.assertEqual(result, {"created": 0, "updated": 1})


class AssociationPolicyTest(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.svc = DeviceService(self.db, self.events)
        self.policy = AssociationPolicy(self.svc.repo)

    def ev(self, calling="CT_SALA2", called="VYONIX", address="192.168.10.25", unknown=False):
        return self.policy.evaluate(calling_ae=calling, called_ae=called, address=address,
                                    local_ae="VYONIX", accept_unknown=unknown)

    def test_rules(self):
        self.assertEqual(self.ev(called="OUTRO").diagnostic, DIAG_CALLED_AE)
        self.assertEqual(self.ev().diagnostic, DIAG_CALLING_AE)          # não cadastrado
        self.assertTrue(self.ev(unknown=True).accepted)                  # opção de implantação
        d = self.svc.create(CT, actor="t")
        self.assertFalse(self.ev().accepted)                             # cadastrado, não autorizado
        self.svc.set_authorized(d.id, True, actor="t")
        decision = self.ev()
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.device_id, d.id)
        self.assertFalse(self.ev(address="10.0.0.9").accepted)           # IP diferente
        self.svc.update(d.id, {"ip_address": None}, actor="t")
        self.assertTrue(self.ev(address="10.0.0.9").accepted)            # sem IP cadastrado: só AE
