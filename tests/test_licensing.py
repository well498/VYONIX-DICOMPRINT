"""Licenciamento v2 — testes obrigatórios 11 a 31, 34 e 35 (prompt definitivo, seção 20).

Relógio, hardware e TPM simulados (``tests/licensing_support.py``); emissão pelo núcleo real do
VYONIX License Manager. Os nomes dos testes trazem o número do requisito (``t11_``…).
"""

from __future__ import annotations

import json
import unittest
from datetime import timedelta

from vyonix_protocol import formats as F
from vyonix_protocol.codec import b64d, b64e

from app.core.contracts import LicenseState
from app.core.errors import ValidationError
from app.licensing.installation import InstallationManager
from tests.helpers import TempDirTestCase
from tests.licensing_support import PASS, Client, Computer, FakeTpm, make_manager


class Base(TempDirTestCase):
    tpm = False

    def setUp(self):
        super().setUp()
        self.pc = Computer(tpm=FakeTpm() if self.tpm else None)
        self.lm, self.admin, self.keys, self.cid = make_manager(self.tmp / "lm", clock=lambda: self.pc.clock.wall)
        self.client = Client(self.pc, self.tmp / "c1", self.keys)
        self.addCleanup(self.lm.close)
        self.addCleanup(lambda: self.client.close())

    def issue(self, client=None, ltype="annual", **kw):
        client = client or self.client
        info = self.lm.import_request(self.admin, client.svc.request_code())
        lic = self.lm.issue(self.admin, info.request_id, self.cid, ltype=ltype, edition="Profissional", **kw)
        return lic

    def activate(self, client=None, ltype="annual", **kw):
        client = client or self.client
        lic = self.issue(client, ltype, **kw)
        st = client.svc.install(lic["document"], actor="técnico")
        return lic, st


class IdentifiersTest(Base):
    def test_t11_hardware_id_combination(self):
        prof = self.client.svc.profile()
        self.assertRegex(prof.hardware_id, r"^VYXH-[0-9A-Z]{5}(-[0-9A-Z]{5}){3}$")
        for c in ("uuid", "board", "system", "disk"):
            self.assertRegex(prof.digests[c], r"^[0-9a-f]{64}$")
        code = self.client.svc.request_code()
        for raw in (self.pc.disk, self.pc.uuid, self.pc.system, self.pc.mac[0]):     # nada original exposto
            self.assertNotIn(raw, json.dumps(F.parse_request(code)))
        # Estável, e muda com qualquer componente forte (mas não com a placa de rede).
        self.assertEqual(self.client.svc.profile(refresh=True).hardware_id, prof.hardware_id)
        self.pc.mac = ["B8:CA:3A:99:99:99"]
        self.assertEqual(self.client.svc.profile(refresh=True).hardware_id, prof.hardware_id)
        self.pc.disk = "OUTRO-DISCO-0001"
        self.assertNotEqual(self.client.svc.profile(refresh=True).hardware_id, prof.hardware_id)

    def test_t11_junk_values_ignored(self):
        self.pc.uuid = "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF"
        self.pc.board = "To be filled by O.E.M."
        prof = self.client.svc.profile(refresh=True)
        self.assertIsNone(prof.digests["uuid"])
        self.assertFalse(prof.available["uuid"])

    def test_t12_installation_id(self):
        a = self.client.svc.installation_id()
        self.assertRegex(a, r"^VYXI-[0-9A-F-]{36}$")
        self.assertEqual(self.client.svc.installation_id(), a)
        self.assertEqual(self.client.settings["system.installation_id"], a)
        self.client.reopen(self.keys)
        self.assertEqual(self.client.svc.installation_id(), a)      # persistente entre execuções
        other = Client(Computer(), self.tmp / "c2", self.keys)
        self.addCleanup(other.close)
        self.assertNotEqual(other.svc.installation_id(), a)


class ActivationTest(Base):
    def test_t13_signed_license(self):
        lic = self.issue()
        doc = json.loads(lic["document"])
        self.assertEqual(doc["format"], "vyonix-license")
        self.assertEqual(doc["key_id"], "teste-01")
        payload = json.loads(b64d(doc["payload"]))
        for k in ("license_id", "product_id", "hardware_id", "installation_id", "features", "issued_at", "expires_at"):
            self.assertTrue(payload.get(k), k)
        self.assertEqual(payload["installation_id"], self.client.svc.installation_id())
        self.assertEqual(payload["hardware_id"], self.client.svc.hardware_id())
        self.assertIn("license.issue", [a["action"] for a in self.lm.audit_log()])
        self.assertEqual(self.lm.verify_audit(), [])

    def test_t14_offline_activation(self):
        self.assertFalse(self.client.svc.allows("printing"))
        lic, st = self.activate(max_devices=3, max_printers=2, features=["storage", "printing"])
        self.assertEqual(st.state, LicenseState.VALID)
        self.assertTrue(self.client.svc.allows("printing"))
        self.assertFalse(self.client.svc.allows("print_scp"))       # recurso não liberado
        self.assertEqual(self.client.svc.device_limit(), 3)
        self.assertEqual(self.client.svc.printer_limit(), 2)
        self.client.reopen(self.keys)                               # sobrevive ao fechamento
        self.assertEqual(self.client.svc.status().state, LicenseState.VALID)

    def test_t15_tampered_license_rejected(self):
        lic = self.issue()
        doc = json.loads(lic["document"])
        payload = json.loads(b64d(doc["payload"]))
        payload["expires_at"] = None                                 # tenta tornar permanente
        doc["payload"] = b64e(json.dumps(payload).encode())
        with self.assertRaisesRegex(ValidationError, "Assinatura digital inválida"):
            self.client.svc.install(json.dumps(doc), actor="t")
        doc2 = json.loads(lic["document"])
        doc2["key_id"] = "chave-falsa"
        with self.assertRaisesRegex(ValidationError, "chave desconhecida"):
            self.client.svc.install(json.dumps(doc2), actor="t")
        with self.assertRaises(ValidationError):
            self.client.svc.install('{"format": "vyonix-license", "v": 2, "payload": "x", "signature": "y"}', actor="t")
        # Licença assinada por outra chave (gerada fora do License Manager oficial)
        from license_manager.paths import LMPaths
        from license_manager.service import LicenseManager
        rogue = LicenseManager(LMPaths(self.tmp / "rogue", "custom"))
        self.addCleanup(rogue.close)
        ra = rogue.initialize("x", "x", "Senha-Forte-123")
        rogue.generate_key(ra, "teste-01", PASS)        # mesmo nome, outra chave
        rogue.unlock_key(ra, PASS)
        rc = rogue.save_customer(ra, {"name": "Pirata"})
        ri = rogue.import_request(ra, self.client.svc.request_code())
        rl = rogue.issue(ra, ri.request_id, rc, ltype="permanent", edition="Profissional")
        with self.assertRaisesRegex(ValidationError, "Assinatura digital inválida"):
            self.client.svc.install(rl["document"], actor="t")
        # Arquivo alterado no banco depois de instalado também é detectado.
        self.client.svc.install(lic["document"], actor="t")
        raw = self.client.db.connection().execute("SELECT raw FROM licenses WHERE status = 'active'").fetchone()[0]
        doc3 = json.loads(raw)
        p3 = json.loads(b64d(doc3["payload"]))
        p3["max_printers"] = 99
        doc3["payload"] = b64e(json.dumps(p3).encode())
        self.client.db.connection().execute("UPDATE licenses SET raw = ? WHERE status = 'active'", (json.dumps(doc3),))
        self.client.svc._invalidate()
        self.assertEqual(self.client.svc.status().state, LicenseState.INVALID)

    def test_t16_other_computer_rejected(self):
        lic = self.issue()
        other_pc = Computer(uuid="11111111-2222-3333-4444-555555555555", board="ASUS|PRIME|X1", system="outro-guid",
                            disk="WD-OUTRO", mac=["00:11:22:33:44:55"])
        other = Client(other_pc, self.tmp / "c2", self.keys)
        self.addCleanup(other.close)
        # copiar o arquivo e também o Installation ID (clonagem) — o hardware não confere
        other.vault.write("installation", {"installation_id": self.client.svc.installation_id(), "state": "active",
                                           "created_at": "x", "origin": "clone", "retired": []})
        with self.assertRaisesRegex(ValidationError, "outro computador"):
            other.svc.install(lic["document"], actor="t")

    def test_t17_other_installation_rejected(self):
        lic = self.issue()
        twin = Client(Computer(), self.tmp / "c2", self.keys)      # mesmo hardware, outra instalação
        self.addCleanup(twin.close)
        v = twin.svc.check(lic["document"])
        self.assertEqual(v.status.state, LicenseState.INSTALLATION_MISMATCH)
        with self.assertRaisesRegex(ValidationError, "outra instalação"):
            twin.svc.install(lic["document"], actor="t")


class TpmTest(Base):
    tpm = True

    def test_t18_tpm_proof_of_possession(self):
        prof = self.client.svc.profile()
        self.assertTrue(prof.digests["tpm"])
        info = self.lm.import_request(self.admin, self.client.svc.request_code())
        self.assertEqual(info.tpm_status, "verified")              # solicitação assinada pelo TPM
        lic = self.lm.issue(self.admin, info.request_id, self.cid, ltype="annual", edition="Profissional")
        st = self.client.svc.install(lic["document"], actor="t")
        self.assertEqual(st.state, LicenseState.VALID)
        self.assertIn("tpm", json.loads(b64d(json.loads(lic["document"])["payload"]))["hw"])
        # Clone: mesmos identificadores e cofre, mas sem a chave do TPM original (outro chip).
        clone_pc = Computer(tpm=FakeTpm(), db_backend=self.pc.db_backend, file_backend=self.pc.file_backend,
                            reg_backend=self.pc.reg_backend)
        clone = Client(clone_pc, self.tmp / "c1", self.keys)
        self.addCleanup(clone.close)
        st2 = clone.svc.status(refresh=True)
        self.assertEqual(st2.state, LicenseState.HARDWARE_MISMATCH)
        self.assertIn("TPM", st2.message)
        # Chave pública copiada, mas o TPM não consegue assinar (chave privada ausente).
        fake = FakeTpm()
        fake.blob = self.pc.tpm.blob
        clone_pc.tpm = fake
        clone.reopen(self.keys)
        st3 = clone.svc.status(refresh=True)
        self.assertEqual(st3.state, LicenseState.HARDWARE_MISMATCH)
        self.assertIn("Prova de posse do TPM falhou", st3.message)

    def test_t18_tampered_request_signature(self):
        data = self.client.svc.request_data()
        data["site"] = "Alterado"
        from license_manager.service import LMError  # noqa: F401
        info = self.lm.import_request(self.admin, F.encode_request(data))
        self.assertEqual(info.tpm_status, "invalid")


class InstallLifecycleTest(Base):
    def reinstall(self, mode: str, *, keep_db: bool = True):
        """Desinstala (opcional) e instala de novo pelo fluxo do instalador."""
        mgr = InstallationManager(self.pc.vault())
        if mode == "fresh":
            self.client.svc.end_activation("desinstalação")
            mgr.uninstall()
        mgr.provision(mode, legacy_id=None)
        self.client.reopen(self.keys)

    def test_t19_t20_uninstall_reinstall_requires_new_license(self):
        lic, _ = self.activate()
        old_id = self.client.svc.installation_id()
        self.reinstall("fresh")
        new_id = self.client.svc.installation_id()
        self.assertNotEqual(new_id, old_id)
        st = self.client.svc.status(refresh=True)
        self.assertEqual(st.state, LicenseState.NOT_ACTIVATED)
        self.assertFalse(self.client.svc.allows("printing"))
        with self.assertRaisesRegex(ValidationError, "outra instalação"):
            self.client.svc.install(lic["document"], actor="t")      # licença anterior não é aceita
        req = F.parse_request(self.client.svc.request_code(reason="reinstall"))
        self.assertEqual(req["installation_id"], new_id)
        self.assertEqual(req["previous_license_id"], None)
        statuses = {r["license_id"]: r["status"] for r in self.client.svc.history()}
        self.assertEqual(statuses[lic["license_id"]], "ended")

    def test_t21_official_update_keeps_license(self):
        lic, _ = self.activate()
        old_id = self.client.svc.installation_id()
        self.reinstall("upgrade")
        self.assertEqual(self.client.svc.installation_id(), old_id)
        self.assertEqual(self.client.svc.status(refresh=True).state, LicenseState.VALID)

    def test_t21_upgrade_from_100_adopts_existing_id(self):
        pc = Computer()
        mgr = InstallationManager(pc.vault())
        rec, what = mgr.provision("upgrade", legacy_id="VYXI-LEGADO")
        self.assertEqual(rec["installation_id"], "VYXI-LEGADO")
        self.assertIn("adotado", what)
        rec2, _ = mgr.provision("fresh")
        self.assertNotEqual(rec2["installation_id"], "VYXI-LEGADO")
        self.assertIn("VYXI-LEGADO", rec2["retired"])
        rec3, _ = InstallationManager(pc.vault()).provision("upgrade", legacy_id="VYXI-LEGADO")
        self.assertEqual(rec3["installation_id"], rec2["installation_id"])   # ID aposentado não volta

    def test_t20_copied_program_without_record_gets_new_id(self):
        self.activate()
        old = self.client.svc.installation_id()
        InstallationManager(self.pc.vault()).uninstall()
        self.client.reopen(self.keys)                                  # executado sem o instalador
        self.assertNotEqual(self.client.svc.installation_id(), old)
        self.assertNotEqual(self.client.svc.status(refresh=True).state, LicenseState.VALID)


class HardwareChangeTest(Base):
    def test_t22_disk_replacement_and_t24_reactivation(self):
        lic, _ = self.activate()
        self.pc.disk = "SSD-NOVO-0002"
        self.client.svc.profile(refresh=True)
        st = self.client.svc.status(refresh=True)
        self.assertEqual(st.state, LicenseState.HARDWARE_MISMATCH)
        self.assertIn("disco do sistema substituído", st.message)
        info = self.lm.import_request(self.admin, self.client.svc.request_code(reason="disk"))
        self.assertTrue(any(r["license_id"] == lic["license_id"] for r in info.related))   # histórico identifica
        with self.assertRaisesRegex(Exception, "motivo"):
            self.lm.reactivate(self.admin, lic["license_id"], info.request_id, "disk", "")
        new = self.lm.reactivate(self.admin, lic["license_id"], info.request_id, "disk", "SSD trocado pela assistência")
        self.assertEqual(new["reissue_of"], lic["license_id"])
        self.assertEqual(new["expires_at"], lic["expires_at"])          # mantém a validade contratada
        self.assertEqual(self.lm.license(lic["license_id"])["status"], "replaced")
        st2 = self.client.svc.install(new["document"], actor="t")
        self.assertEqual(st2.state, LicenseState.VALID)
        hist = self.lm.customer_history(self.cid)
        self.assertEqual(hist["reactivations"][0]["reason_code"], "disk")
        self.assertEqual(len(hist["licenses"]), 2)

    def test_t23_motherboard_replacement(self):
        self.activate()
        self.pc.board = "Gigabyte|B550M|SN-NOVA"
        self.pc.uuid = "99999999-8888-7777-6666-555555555555"
        self.client.svc.profile(refresh=True)
        st = self.client.svc.status(refresh=True)
        self.assertEqual(st.state, LicenseState.HARDWARE_MISMATCH)
        self.assertIn("placa-mãe diferente", st.message)

    def test_unreadable_component_tolerated_with_nic(self):
        self.activate()
        self.pc.disk = None                                          # leitura falhou (WMI)
        self.client.svc.profile(refresh=True)
        self.assertEqual(self.client.svc.status(refresh=True).state, LicenseState.VALID)
        self.pc.mac = []
        self.client.svc.profile(refresh=True)
        self.assertEqual(self.client.svc.status(refresh=True).state, LicenseState.HARDWARE_MISMATCH)


class DemoTest(Base):
    def test_t25_demo_120_hours(self):
        st = self.client.svc.start_demo(actor="t")
        self.assertEqual(st.state, LicenseState.DEMO)
        self.assertAlmostEqual(st.remaining_s, 120 * 3600, delta=1)
        self.assertTrue(self.client.svc.allows("printing"))
        self.assertEqual(self.client.svc.mark_text(), "VYONIX DICOM Print — DEMONSTRAÇÃO")
        self.pc.clock.advance(hours=100)
        st = self.client.svc.status(refresh=True)
        self.assertEqual(st.state, LicenseState.DEMO)
        self.assertIsNotNone(st.warning)                             # aviso nas últimas 24 h
        self.assertAlmostEqual(st.remaining_s, 20 * 3600, delta=60)
        self.pc.clock.advance(hours=20, seconds=1)
        st = self.client.svc.status(refresh=True)
        self.assertEqual(st.state, LicenseState.DEMO_EXPIRED)
        self.assertFalse(self.client.svc.allows("printing"))
        with self.assertRaisesRegex(ValidationError, "já foi utilizada"):
            self.client.svc.start_demo(actor="t")
        # conversão para licença comercial preserva as configurações (mesmo banco)
        self.client.db.connection().execute("INSERT INTO settings(key, value_json, updated_at, updated_by) "
                                            "VALUES ('printing.copies', '3', 'x', 't') ON CONFLICT DO NOTHING")
        _, st = self.activate()
        self.assertEqual(st.state, LicenseState.VALID)
        self.assertEqual(self.client.db.connection().execute(
            "SELECT value_json FROM settings WHERE key = 'printing.copies'").fetchone()[0], "3")

    def test_t26_restart_during_demo(self):
        self.client.svc.start_demo(actor="t")
        self.pc.clock.advance(hours=10)
        self.client.reopen(self.keys)                                # fechou e abriu
        self.pc.clock.reboot(off=timedelta(hours=14))                # computador desligado 14 h
        self.client.reopen(self.keys)
        st = self.client.svc.status(refresh=True)
        self.assertAlmostEqual(st.remaining_s, (120 - 24) * 3600, delta=300)

    def test_t25_reinstall_and_clearing_settings_do_not_renew_demo(self):
        self.client.svc.start_demo(actor="t")
        self.pc.clock.advance(hours=121)
        mgr = InstallationManager(self.pc.vault())
        mgr.uninstall()
        self.pc.db_backend.data.clear()                              # dados do VYONIX removidos na desinstalação
        mgr.provision("fresh")
        fresh = Client(self.pc, self.tmp / "c-novo", self.keys)      # banco novo
        self.addCleanup(fresh.close)
        self.assertEqual(fresh.svc.status(refresh=True).state, LicenseState.DEMO_EXPIRED)
        with self.assertRaises(ValidationError):
            fresh.svc.start_demo(actor="t")

    def test_tampered_demo_record_blocks(self):
        self.client.svc.start_demo(actor="t")
        for b in (self.pc.db_backend, self.pc.file_backend, self.pc.reg_backend):
            doc = json.loads(b.data["demo"])
            doc["r"]["started_at"] = "2030-01-01T00:00:00.000Z"      # tenta "renovar" editando o registro
            b.data["demo"] = json.dumps(doc)
        st = self.client.svc.status(refresh=True)
        self.assertEqual(st.state, LicenseState.SUSPENDED)
        self.assertIn("revalidação administrativa", st.message)

    def test_signed_demo_and_reuse_control(self):
        lic, st = self.activate(ltype="demo")
        self.assertEqual(st.state, LicenseState.DEMO)
        self.assertEqual(st.kind, "demo_signed")
        self.pc.clock.advance(hours=121)
        self.assertEqual(self.client.svc.status(refresh=True).state, LicenseState.DEMO_EXPIRED)
        with self.assertRaisesRegex(Exception, "já recebeu DEMO"):
            self.issue(ltype="demo")
        self.client.svc.remove(actor="t")
        lic2 = self.issue(ltype="demo", demo_override="nova avaliação autorizada pela diretoria")
        self.assertEqual(lic2["type"], "demo")


class TimeTest(Base):
    def test_t27_clock_rollback_during_run(self):
        self.activate(ltype="monthly")
        self.pc.clock.advance(days=20)
        self.client.svc.status(refresh=True)
        self.pc.clock.shift_wall(days=-15)                           # volta a data com o VYONIX aberto
        st = self.client.svc.status(refresh=True)
        self.assertEqual(st.state, LicenseState.SUSPENDED)
        self.assertFalse(self.client.svc.allows("printing"))
        kinds = [r[0] for r in self.client.db.connection().execute("SELECT kind FROM time_integrity_log")]
        self.assertIn("rollback", kinds)
        self.assertIn("backward_jump", kinds)
        self.pc.clock.shift_wall(days=15)                            # corrige o relógio
        self.assertEqual(self.client.svc.status(refresh=True).state, LicenseState.VALID)

    def test_t27_rollback_while_off_and_admin_revalidation(self):
        self.client.svc.start_demo(actor="t")
        self.pc.clock.advance(hours=110)
        self.client.svc.status(refresh=True)
        self.pc.clock.reboot()
        self.pc.clock.shift_wall(hours=-100)                         # voltou a data com o PC desligado
        self.client.reopen(self.keys)
        st = self.client.svc.status(refresh=True)
        self.assertEqual(st.state, LicenseState.SUSPENDED)
        self.assertIn("anterior ao último horário confiável", st.message)
        # recuperação administrativa: diagnóstico → License Manager → revalidação assinada
        diag = json.dumps(self.client.svc.diagnostic())
        self.assertNotIn(self.pc.disk, diag)
        rv = self.lm.revalidate(self.admin, diag, reason="relógio da BIOS reiniciado", actions=["time"],
                                trusted_time=self.pc.clock.wall)
        msg = self.client.svc.apply_revalidation(rv["document"], actor="t")
        self.assertIn("horário confiável", msg)
        with self.assertRaisesRegex(ValidationError, "já foi aplicada"):
            self.client.svc.apply_revalidation(rv["document"], actor="t")
        st = self.client.svc.status(refresh=True)
        # a revalidação não devolve tempo de DEMO: a contagem já consumida é preservada
        self.assertIn(st.state, (LicenseState.DEMO, LicenseState.DEMO_EXPIRED))

    def test_t27_rollback_does_not_extend_validity(self):
        self.activate(ltype="monthly")
        self.pc.clock.advance(days=29, hours=20)
        self.client.svc.status(refresh=True)
        self.pc.clock.shift_wall(hours=-20)                          # dentro da tolerância: não bloqueia...
        st = self.client.svc.status(refresh=True)
        self.assertEqual(st.state, LicenseState.VALID)
        self.pc.clock.advance(hours=20)                              # ...mas o tempo efetivo não voltou
        self.assertEqual(self.client.svc.status(refresh=True).state, LicenseState.EXPIRED)

    def test_t28_future_date_gives_no_extra_time(self):
        self.client.svc.start_demo(actor="t")
        self.pc.clock.advance(hours=10)
        self.client.svc.status(refresh=True)
        self.pc.clock.shift_wall(days=30)                            # adianta o relógio
        st = self.client.svc.status(refresh=True)
        self.assertEqual(st.state, LicenseState.DEMO_EXPIRED)        # efeito só contra o usuário
        kinds = [r[0] for r in self.client.db.connection().execute("SELECT kind FROM time_integrity_log")]
        self.assertIn("forward_jump", kinds)
        self.pc.clock.shift_wall(days=-30)                           # volta: nada bloqueado, nada ganho
        st = self.client.svc.status(refresh=True)
        self.assertEqual(st.state, LicenseState.DEMO)
        self.assertAlmostEqual(st.remaining_s, 110 * 3600, delta=600)

    def test_t28_future_date_with_app_closed_same_boot(self):
        self.client.svc.start_demo(actor="t")
        self.client.svc.status(refresh=True)
        self.pc.clock.shift_wall(days=10)                            # VYONIX fechado, mesma inicialização
        self.client.reopen(self.keys)
        self.client.svc.status(refresh=True)
        self.pc.clock.shift_wall(days=-10)
        self.client.reopen(self.keys)
        st = self.client.svc.status(refresh=True)
        self.assertEqual(st.state, LicenseState.DEMO)

    def test_t29_legitimate_corrections(self):
        self.activate(ltype="annual")
        self.pc.clock.advance(hours=5)
        self.client.svc.status(refresh=True)
        self.pc.clock.shift_wall(minutes=-3)                         # NTP
        self.assertEqual(self.client.svc.status(refresh=True).state, LicenseState.VALID)
        self.pc.clock.shift_wall(hours=-3)                           # fuso horário configurado errado e corrigido
        self.assertEqual(self.client.svc.status(refresh=True).state, LicenseState.VALID)
        self.pc.clock.reboot()
        self.pc.clock.shift_wall(hours=-1)                           # horário de verão aplicado pela BIOS/local
        self.client.reopen(self.keys)
        self.assertEqual(self.client.svc.status(refresh=True).state, LicenseState.VALID)

    def test_t29_long_sleep_is_not_tampering(self):
        self.activate(ltype="annual")
        self.client.svc.status(refresh=True)
        self.pc.clock.advance(days=3)                                # suspensão: relógios andam juntos
        st = self.client.svc.status(refresh=True)
        self.assertEqual(st.state, LicenseState.VALID)
        kinds = [r[0] for r in self.client.db.connection().execute("SELECT kind FROM time_integrity_log")]
        self.assertNotIn("forward_jump", kinds)

    def test_floor_before_signed_issue_date(self):
        lic = self.issue()
        self.pc.clock.shift_wall(days=-30)                           # instala com a data antes da emissão
        self.client.reopen(self.keys)
        with self.assertRaises(ValidationError):
            self.client.svc.install(lic["document"], actor="t")


class ValidityTest(Base):
    def test_t30_commercial_expiry(self):
        lic, st = self.activate(ltype="quarterly")
        self.assertEqual(F.parse_time(lic["expires_at"]).astimezone(F.BRT).strftime("%Y-%m-%d %H:%M"),
                         "2026-12-31 23:59")
        self.pc.clock.advance(days=80)
        st = self.client.svc.status(refresh=True)
        self.assertEqual(st.state, LicenseState.VALID)
        self.assertIsNotNone(st.warning)                             # aviso de vencimento
        self.pc.clock.advance(days=12)
        st = self.client.svc.status(refresh=True)
        self.assertEqual(st.state, LicenseState.EXPIRED)
        self.assertFalse(self.client.svc.allows("storage"))
        renewed = self.lm.renew(self.admin, lic["license_id"], ltype="annual")
        self.assertEqual(self.client.svc.install(renewed["document"], actor="t").state, LicenseState.VALID)
        self.assertEqual(self.lm.license(lic["license_id"])["status"], "superseded")

    def test_t30_types(self):
        for t, months in (("monthly", 1), ("semiannual", 6)):
            lic = self.lm._issue(self.admin, customer_id=self.cid, product_id=F.PRODUCT_ID, edition="Profissional",
                                 ltype=t, hw={"system": "a" * 64, "uuid": "b" * 64}, hardware_id=F.hardware_id(
                                     {"system": "a" * 64, "uuid": "b" * 64}), installation_id=f"VYXI-{t}",
                                 starts=None, custom_end=None, max_devices=None, max_printers=None,
                                 features=list(F.FEATURES), notes=None, operation="issue", request_id=None,
                                 reissue_of=None, reason_code=None, reason_text=None)
            self.assertEqual(F.parse_time(lic["expires_at"]), F.add_months(self.pc.clock.wall, months))

    def test_t31_permanent(self):
        lic, st = self.activate(ltype="permanent")
        self.assertIsNone(lic["expires_at"])
        self.pc.clock.advance(days=3650)
        self.assertEqual(self.client.svc.status(refresh=True).state, LicenseState.VALID)
        self.pc.disk = "OUTRO"                                       # continua sujeita ao hardware
        self.client.svc.profile(refresh=True)
        self.assertEqual(self.client.svc.status(refresh=True).state, LicenseState.HARDWARE_MISMATCH)

    def test_revocation_list(self):
        lic, _ = self.activate()
        self.lm.revoke(self.admin, lic["license_id"], "inadimplência")
        rl = self.lm.revocation_list(self.admin)
        self.client.svc.apply_revocation(rl["document"], actor="t")
        self.assertEqual(self.client.svc.status(refresh=True).state, LicenseState.REVOKED)
        with self.assertRaisesRegex(ValidationError, "mais antiga"):
            self.client.svc.apply_revocation(rl["document"], actor="t")


class ManagerSecurityTest(Base):
    def test_t34_private_key_protection(self):
        row = self.lm.db.conn().execute("SELECT private_pem FROM signing_keys").fetchone()
        self.assertTrue(bytes(row[0]).startswith(b"-----BEGIN ENCRYPTED PRIVATE KEY-----"))
        raw = self.lm.paths.db_file.read_bytes()
        self.assertNotIn(b"BEGIN PRIVATE KEY", raw)
        from license_manager.service import LMError
        self.lm.lock_key()
        with self.assertRaisesRegex(LMError, "Desbloqueie"):
            self.issue()
        with self.assertRaisesRegex(LMError, "incorreta"):
            self.lm.unlock_key(self.admin, "errada-errada")
        viewer_pw = "Consulta-123x"
        self.lm.create_user(self.admin, "leitor", "Leitor", "viewer", viewer_pw)
        viewer = self.lm.login("leitor", viewer_pw)
        from license_manager.security import PermissionDenied
        with self.assertRaises(PermissionDenied):
            self.lm.unlock_key(viewer, PASS)
        with self.assertRaises(PermissionDenied):
            self.lm.generate_key(viewer, "x", PASS)
        # o pacote do DICOM Print não contém o License Manager nem funções de emissão
        import app.licensing.license as L
        self.assertFalse(hasattr(L.LicenseService, "issue"))
        with open(L.__file__, encoding="utf-8") as fh:
            self.assertNotIn("sign_ed25519", fh.read())

    def test_t34_key_rotation(self):
        lic1, _ = self.activate()
        k2 = self.lm.generate_key(self.admin, "teste-02", PASS)
        self.assertEqual(k2["status"], "standby")
        self.lm.set_key_status(self.admin, "teste-02", "active")
        self.lm.unlock_key(self.admin, PASS)
        self.assertIn('"teste-02"', self.lm.export_public_line("teste-02"))
        self.client.svc.public_keys["teste-02"] = k2["public_hex"]   # atualização oficial com a nova chave
        renewed = self.lm.renew(self.admin, lic1["license_id"], ltype="annual")
        self.assertEqual(json.loads(renewed["document"])["key_id"], "teste-02")
        self.assertEqual(self.client.svc.install(renewed["document"], actor="t").state, LicenseState.VALID)

    def test_login_lockout_and_audit_chain(self):
        from license_manager.security import AuthError
        for _ in range(5):
            with self.assertRaises(AuthError):
                self.lm.login("admin", "errada")
        with self.assertRaisesRegex(AuthError, "bloqueado"):
            self.lm.login("admin", "Senha-Forte-123")
        self.assertEqual(self.lm.verify_audit(), [])
        self.lm.db.conn().execute("UPDATE audit SET details = '{}' WHERE id = 3")
        self.assertIn(3, self.lm.verify_audit())

    def test_t35_backup_restore(self):
        from license_manager import backup as bk
        lic = self.issue()
        dest = self.tmp / "lm.vylmbak"
        self.lm.backup(self.admin, dest, "frase-do-backup-1")
        blob = dest.read_bytes()
        self.assertNotIn(b"Cl\xc3\xadnica Teste", blob)              # dados pessoais cifrados
        self.assertNotIn(lic["license_id"].encode(), blob)
        with self.assertRaises(bk.BackupError):
            self.lm.restore(self.admin, dest, "frase-errada-xx")
        self.lm.revoke(self.admin, lic["license_id"], "teste")
        self.lm.restore(self.admin, dest, "frase-do-backup-1")
        self.assertEqual(self.lm.license(lic["license_id"])["status"], "active")
        tampered = bytearray(blob)
        tampered[-5] ^= 1
        (self.tmp / "x.vylmbak").write_bytes(bytes(tampered))
        with self.assertRaisesRegex(bk.BackupError, "alterado"):
            self.lm.restore(self.admin, self.tmp / "x.vylmbak", "frase-do-backup-1")

    def test_t35_corrupted_database_detected(self):
        from license_manager.db import Database, DatabaseCorrupt
        bad = self.tmp / "ruim.db"
        bad.write_bytes(b"SQLite format 3\x00" + b"\xff" * 4096)
        with self.assertRaises(DatabaseCorrupt):
            Database(bad).migrate()

    def test_lgpd_anonymize(self):
        self.activate()
        self.lm.anonymize_customer(self.admin, self.cid)
        c = self.lm.customer(self.cid)
        self.assertIsNone(c["document"])
        self.assertIn("anonimizado", c["name"])
        self.assertEqual(len(self.lm.customer_history(self.cid)["licenses"]), 1)

    def test_dashboard(self):
        self.activate(ltype="monthly")
        self.pc.clock.advance(days=5)
        d = self.lm.dashboard()
        self.assertEqual(d["licenses_active"], 1)
        self.assertEqual(d["expiring_30"], 1)
        self.assertTrue(d["audit_ok"])


class DevModeTest(Base):
    def test_not_enforced_in_dev(self):
        dev = Client(Computer(), self.tmp / "dev", self.keys, enforced=False)
        self.addCleanup(dev.close)
        self.assertTrue(dev.svc.allows("printing"))
        self.assertEqual(dev.svc.status().state, LicenseState.NOT_ACTIVATED)


if __name__ == "__main__":
    unittest.main()
