"""Licenciamento modular (v3) do Core: emissão real pelo License Manager, verificação real no Core.

O "computador" (identificadores de hardware, relógio, cofre) vem do apoio de testes do licenciamento do
DICOM Print (``tests.licensing_support``); assinatura, banco PostgreSQL e License Manager são reais.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from tests_platform.support import new_org, require_db


def setUpModule():
    global db
    db = require_db()


class Base(unittest.TestCase):
    def setUp(self):
        from tests.licensing_support import Computer, make_manager
        self.tmp = Path(tempfile.mkdtemp(prefix="vyx-lic-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.pc = Computer()
        self.lm, self.admin, self.keys, self.cid = make_manager(self.tmp / "lm", clock=lambda: self.pc.clock.wall)
        self.addCleanup(self.lm.close)
        self.lic = self.licensing(self.pc)
        self.t = new_org(db)

    def licensing(self, pc):
        from app.licensing.hardware import HardwareProvider
        from app.licensing.installation import InstallationManager
        from app.licensing.time_integrity import TimeIntegrity
        from vyonix.licensing.service import Licensing, Machine
        vault = pc.vault()
        m = Machine(vault=vault, hardware=HardwareProvider(pc.tpm, collector=pc.raw), tpm=pc.tpm,
                    installation=InstallationManager(vault), time=TimeIntegrity(vault, pc.clock))
        return Licensing(m, public_keys=self.keys, key_scopes={k: ("license", "authorization", "revalidation",
                                                                    "revocation") for k in self.keys})

    def request_id(self, lic=None, **kw):
        lic = lic or self.lic
        r = lic.request(modules=kw.pop("modules", ["core", "print"]), demo_days=kw.pop("demo_days", None),
                        organization="Clínica Teste", contact={"name": "Ana", "email": "ana@exemplo.com"})
        return self.lm.import_request(self.admin, r["code"]).request_id

    def issue(self, ltype="annual", modules=None, features=None, **kw):
        return self.lm.issue(self.admin, self.request_id(), self.cid, ltype=ltype, edition="Profissional",
                             modules=modules, features=features, **kw)

    def apply(self, doc, tenant=None):
        with db.session(tenant or self.t) as s:
            return self.lic.install(s, doc, actor="admin")

    def status(self, tenant=None):
        with db.session(tenant or self.t) as s:
            return {k: v for k, v in self.lic.status(s, refresh=True).items()}


class LicensingV3(Base):
    def test_request_carries_modules_and_no_clinical_data(self):
        from vyonix_protocol import formats as F
        r = self.lic.request(modules=["core", "ris"], demo_days=15, organization="Clínica Teste",
                             contact={"name": "Ana", "email": "a@x.com", "paciente": "não vai"})
        data = F.parse_request(r["code"])
        self.assertEqual(data["platform"]["modules"], ["core", "ris"])
        self.assertEqual(data["platform"]["demo_days"], 15)
        self.assertNotIn("paciente", data["platform"]["contact"])
        self.assertEqual(data["installation_id"], self.lic.installation_id())

    def test_v2_license_grants_core_and_print(self):
        lic = self.issue("annual")                      # licença v2 (sem módulos)
        out = self.apply(lic["document"])
        self.assertEqual(set(out["changes"]), {"core", "print"})
        st = self.status()
        self.assertTrue(st["core"].licensed and st["print"].licensed)
        self.assertEqual(st["core"].kind, "subscription")
        self.assertFalse(st["ris"].licensed)

    def test_v3_modules_demo_extension_conversion(self):
        from vyonix_protocol import formats as F
        lic = self.issue("annual", modules={"core": {"kind": "contract", "limits": {"users": 5}},
                                            "report": {"kind": "demo", "days": 15}})
        p = F.parse_signed(lic["document"], F.LICENSE_FORMAT).payload
        self.assertEqual(p["schema"], 3)
        self.assertNotIn("print", p["modules"])
        self.apply(lic["document"])
        st = self.status()
        self.assertEqual((st["report"].kind, st["report"].state, st["report"].licensed), ("demo", "demo", True))
        self.assertEqual(st["core"].limits, {"users": 5})
        self.assertTrue(st["print"].licensed)                 # recursos do Print = módulo PRINT
        self.pc.clock.advance(days=16)
        st = self.status()
        self.assertEqual(st["report"].state, "demo_expired")
        self.assertTrue(st["core"].licensed)
        # prorrogação: mesmo grant_id, 30 dias contados da ativação original
        ext = self.lm.amend_modules(self.admin, lic["license_id"], {"core": {"kind": "contract",
                                                                            "limits": {"users": 5}},
                                                                   "report": {"kind": "demo", "days": 30}},
                                    reason="prorrogação comercial")
        out = self.apply(ext["document"])
        self.assertEqual(out["changes"]["report"], "extended")
        st = self.status()
        self.assertEqual(st["report"].state, "demo")
        # conversão para o contrato
        conv = self.lm.amend_modules(self.admin, ext["license_id"], {"core": {"kind": "contract"},
                                                                     "report": {"kind": "contract"}},
                                     reason="cliente contratou")
        out = self.apply(conv["document"])
        self.assertEqual(out["changes"]["report"], "converted")
        st = self.status()
        self.assertEqual((st["report"].kind, st["report"].licensed), ("subscription", True))
        self.assertEqual(conv["expires_at"], lic["expires_at"])          # contrato inalterado

    def test_demo_cannot_restart_after_database_reset(self):
        lic = self.issue("annual", modules={"core": {"kind": "contract"}, "ris": {"kind": "demo", "days": 5}})
        self.apply(lic["document"])
        self.pc.clock.advance(days=6)
        other = new_org(db)                    # banco "novo" (reinstalação), mesmo computador e cofre
        self.apply(lic["document"], other)
        self.assertEqual(self.status(other)["ris"].state, "demo_expired")

    def test_activation_deadline(self):
        lic = self.issue("annual", modules={"core": {"kind": "contract"}, "ris": {"kind": "demo", "days": 5}})
        self.pc.clock.advance(days=31)
        from vyonix.errors import ValidationFailed
        with self.assertRaises(ValidationFailed) as cm:
            self.apply(lic["document"])
        self.assertIn("prazo para ativar", str(cm.exception))

    def test_second_module_demo_needs_justification(self):
        from license_manager.service import LMError
        lic = self.issue("annual", modules={"core": {"kind": "contract"}, "ris": {"kind": "demo", "days": 5}})
        with self.assertRaises(LMError):
            self.lm.amend_modules(self.admin, lic["license_id"], {"core": {"kind": "contract"},
                                                                  "ris": {"kind": "demo", "days": 5,
                                                                          "new_trial": True}}, reason="nova")
        self.lm.amend_modules(self.admin, lic["license_id"], {"core": {"kind": "contract"},
                                                              "ris": {"kind": "demo", "days": 5, "new_trial": True}},
                              reason="nova", demo_override="aprovado pela diretoria")

    def test_rejections(self):
        from vyonix.errors import Conflict, ValidationFailed
        lic = self.issue("annual")
        doc = json.loads(lic["document"])
        doc["payload"] = doc["payload"][:-4] + "AAAA"
        with self.assertRaises(ValidationFailed):
            self.apply(json.dumps(doc))
        self.apply(lic["document"])
        with self.assertRaises(Conflict):
            self.apply(lic["document"])
        self.pc.clock.advance(hours=1)
        newer = self.lm.renew(self.admin, lic["license_id"], ltype="annual")
        self.apply(newer["document"])
        with self.assertRaises(Conflict):                  # reaplicar a anterior (mais antiga): recusada
            self.apply(lic["document"].replace("\n", "\r\n"))
        # outro computador
        from tests.licensing_support import Computer
        pc2 = Computer(uuid="0000-OUTRO", board="outra placa", system="outro", disk="outro-disco",
                       mac=["00:11:22:33:44:55"])
        lic2 = self.licensing(pc2)
        with self.assertRaises(ValidationFailed):
            with db.session(new_org(db)) as s:
                lic2.install(s, newer["document"], actor="x")

    def test_restricted_key_refuses_forged_document(self):
        """Incidente de chave: com a chave sob restrição, só os documentos legítimos dela passam."""
        from vyonix.errors import ValidationFailed
        from vyonix_protocol import formats as F
        lic = self.issue("annual")
        key_id = json.loads(lic["document"])["key_id"]
        out = self.lm.export_key_restriction(self.admin, key_id, self.tmp / "exp")
        self.lic.restricted_keys = {key_id: frozenset(out["hashes"])}
        payload = dict(F.parse_signed(lic["document"], F.LICENSE_FORMAT).payload)
        payload["expires_at"] = "2099-12-31T23:59:59Z"
        _k, forged = self.lm._sign_doc(F.LICENSE_FORMAT, payload)
        with self.assertRaisesRegex(ValidationFailed, "retirada por segurança"):
            self.apply(forged)
        self.apply(lic["document"])

    def test_limits(self):
        from vyonix.errors import NotLicensed
        with db.session(self.t) as s:                      # sem licença: limite de instalação
            self.lic.enforce_limit(s, "core", "users", 3)
            with self.assertRaises(NotLicensed):
                self.lic.enforce_limit(s, "core", "sites", 2)
        lic = self.issue("annual", modules={"core": {"kind": "contract", "limits": {"users": 2, "sites": 3}}})
        self.apply(lic["document"])
        with db.session(self.t) as s:
            self.lic.enforce_limit(s, "core", "sites", 3)
            with self.assertRaises(NotLicensed):
                self.lic.enforce_limit(s, "core", "users", 3)

    def test_commercial_suspension_keeps_clinical_data(self):
        from vyonix.clinical import service as clinical
        lic = self.issue("monthly", modules={"core": {"kind": "contract"}})
        self.apply(lic["document"])
        with db.session(self.t) as s:
            pid = clinical.create_patient(s, name="PACIENTE TESTE", actor="t").id
        sub = self.lm.commercial.subscription(lic["license_id"])
        due = sub["paid_until"]
        from vyonix_protocol import formats as F
        self.pc.clock.advance(seconds=(F.parse_time(due) + timedelta(days=2) - self.pc.clock.wall).total_seconds())
        self.lm.commercial.evaluate_all()                  # avisos de atraso registrados (exigidos antes da suspensão)
        self.pc.clock.advance(days=7)
        self.lm.commercial.suspend_now(self.lm.actor(self.admin), sub["id"], "inadimplência confirmada",
                                       operational_ack=True)
        doc = self.lm.offline_authorization(self.admin, lic["license_id"])["document"]
        with db.session(self.t) as s:
            self.lic.apply_authorization(doc, actor="admin", s=s)
        st = self.status()
        self.assertEqual(st["core"].state, "suspended")
        self.assertFalse(st["core"].licensed)
        with db.session(self.t) as s:                      # dados clínicos continuam acessíveis
            self.assertEqual(clinical.get_patient(s, pid).name, "PACIENTE TESTE")
        with self.assertRaises(Exception):                 # mesma autorização não vale duas vezes
            with db.session(self.t) as s:
                self.lic.apply_authorization(doc, actor="admin", s=s)

    def test_print_accepts_v3_license(self):
        from tests.licensing_support import Client
        from app.core.contracts import LicenseState
        client = Client(self.pc, self.tmp / "print", self.keys)
        self.addCleanup(client.close)
        self.assertEqual(client.svc.installation_id(), self.lic.installation_id())   # identidade compartilhada
        lic = self.issue("annual", modules={"core": {"kind": "contract"}, "ris": {"kind": "demo", "days": 15}})
        st = client.svc.install(lic["document"], actor="técnico")
        self.assertEqual(st.state, LicenseState.VALID)
        self.assertTrue(client.svc.allows("printing"))


if __name__ == "__main__":
    unittest.main()
