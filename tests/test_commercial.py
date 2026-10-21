"""Licenciamento comercial por assinatura — testes obrigatórios 1 a 30 (prompt consolidado, seção 22).

Os nomes trazem o número do requisito (``c01_``…). Emissão e gestão comercial pelo núcleo real do
VYONIX License Manager; validação online pelo VYONIX License Server real (HTTPS em 127.0.0.1, certificado
fixado); verificação pelo VYONIX DICOM Print real. Relógio, hardware e TPM simulados como nos demais
testes de licenciamento (``tests/licensing_support.py``); os testes 21 a 28 usam o aplicativo completo
(recepção DICOM, fila, VYONIX Reception) com o relógio do sistema.
"""

from __future__ import annotations

import json
import os
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from vyonix_protocol import crypto
from vyonix_protocol import formats as F
from vyonix_commercial.engine import Actor, CommercialError
from vyonix_commercial.states import iso

from app.core.contracts import LicenseState
from app.core.errors import ValidationError
from tests.helpers import TempDirTestCase
from tests.licensing_support import Client, Computer, make_manager

try:
    import pynetdicom  # noqa: F401
    HAS_NET = True
except ImportError:
    HAS_NET = False


class Base(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.pc = Computer()
        self.lm, self.admin, self.keys, self.cid = make_manager(self.tmp / "lm", clock=lambda: self.pc.clock.wall)
        self.addCleanup(self.lm.close)
        self.client = Client(self.pc, self.tmp / "c1", self.keys)
        self.addCleanup(lambda: self.client.close())
        self.actor = self.lm.actor(self.admin)
        self.lm.create_user(self.admin, "fin", "Financeiro", "financial", "Financeiro-123")
        self.fin = self.lm.login("fin", "Financeiro-123")

    def issue(self, ltype="monthly", **kw):
        info = self.lm.import_request(self.admin, self.client.svc.request_code())
        return self.lm.issue(self.admin, info.request_id, self.cid, ltype=ltype, edition="Profissional", **kw)

    def activate(self, ltype="monthly", **kw):
        lic = self.issue(ltype, **kw)
        return lic, self.client.svc.install(lic["document"], actor="técnico")

    def st(self):
        return self.client.svc.status(refresh=True)

    def sub(self, lid):
        return self.lm.commercial.subscription(lid)

    def auth_file(self, lid):
        return self.lm.offline_authorization(self.admin, lid)["document"]

    def at_due(self, lid, delta=timedelta(0)):
        """Leva o relógio (computador e License Manager) até o vencimento + ``delta``."""
        due = datetime.fromisoformat(self.sub(lid)["paid_until"].replace("Z", "+00:00"))
        self.pc.clock.advance(seconds=(due + delta - self.pc.clock.wall).total_seconds())

    def overdue_and_suspend(self, lid, *, schedule=False):
        self.at_due(lid, timedelta(days=2))
        self.lm.commercial.evaluate_all()                         # avisos registrados (atraso)
        self.at_due(lid, timedelta(days=8))                       # fim da carência de 7 dias
        sid = self.sub(lid)["id"]
        if schedule:
            return self.lm.commercial.schedule_suspension(self.actor, sid, self.pc.clock.wall + timedelta(days=2),
                                                          "inadimplência confirmada", operational_ack=True)
        return self.lm.commercial.suspend_now(self.actor, sid, "inadimplência confirmada", operational_ack=True)


# ============================================================================ 1–6: ciclo da assinatura
class SubscriptionCycleTest(Base):
    def test_c01_monthly_license_active(self):
        lic, st = self.activate("monthly")
        self.assertEqual((st.state, st.commercial), (LicenseState.VALID, "active"))
        self.assertTrue(self.client.svc.allows("storage"))
        payload = F.parse_signed(lic["document"], F.LICENSE_FORMAT).payload
        self.assertEqual(payload["policy"]["grace_days"], 7)
        self.assertEqual(payload["policy"]["warn_days"], 5)
        s = self.sub(lic["license_id"])
        self.assertEqual((s["plan_code"], s["state"], s["customer_document"]), ("monthly", "active",
                                                                                "12.345.678/0001-90"))
        self.assertEqual(s["paid_until"], lic["expires_at"])

    def test_c02_warning_before_due(self):
        lic, _ = self.activate()
        self.at_due(lic["license_id"], -timedelta(days=6))
        self.assertEqual(self.st().commercial, "active")
        self.at_due(lic["license_id"], -timedelta(days=4))
        st = self.st()
        self.assertEqual((st.state, st.commercial), (LicenseState.VALID, "due_soon"))
        self.assertIn("vence em", st.warning)
        self.assertIsNone(st.user_notice)                       # recepção não vê questão financeira
        self.lm.commercial.evaluate_all()
        kinds = [n["kind"] for n in self.lm.commercial.notifications(self.sub(lic["license_id"])["id"])]
        self.assertIn("due_warning", kinds)

    def test_c03_payment_overdue(self):
        lic, _ = self.activate()
        self.at_due(lic["license_id"], timedelta(days=3))
        st = self.st()
        self.assertEqual((st.state, st.commercial), (LicenseState.VALID, "overdue"))
        self.assertIn("vencida", st.admin_notice)
        self.assertTrue(self.client.svc.allows("printing"))
        s = self.sub(lic["license_id"])
        self.assertEqual(s["state"], "overdue")
        self.assertGreaterEqual(s["days_overdue"], 3)

    def test_c04_grace_period_and_extension(self):
        lic, _ = self.activate()
        lid = lic["license_id"]
        sid = self.sub(lid)["id"]
        self.at_due(lid, timedelta(days=6))
        self.assertEqual(self.st().commercial, "overdue")                     # dentro da carência
        fin = self.lm.actor(self.fin)
        with self.assertRaisesRegex(CommercialError, "1 a 30"):
            self.lm.commercial.grant_grace(fin, sid, 45, "acordo")
        with self.assertRaisesRegex(CommercialError, "não pode conceder"):
            self.lm.commercial.grant_grace(Actor("sup", "support"), sid, 5, "acordo")
        s = self.lm.commercial.grant_grace(fin, sid, 10, "acordo de pagamento")
        self.client.svc.import_authorization(self.auth_file(lid), actor="admin")
        self.at_due(lid, timedelta(days=12))                                  # além da carência original
        st = self.st()
        self.assertEqual((st.state, st.commercial), (LicenseState.VALID, "overdue"))
        self.assertTrue(s["grace_extra_until"])
        self.at_due(lid, timedelta(days=17))
        self.assertEqual(self.st().state, LicenseState.EXPIRED)

    def test_c05_scheduled_suspension(self):
        lic, _ = self.activate()
        lid = lic["license_id"]
        sid = self.sub(lid)["id"]
        self.at_due(lid, timedelta(days=2))
        e = self.lm.commercial
        with self.assertRaisesRegex(CommercialError, "avisos|Nenhum aviso"):
            e.schedule_suspension(self.actor, sid, self.pc.clock.wall + timedelta(days=9), "x", operational_ack=True)
        e.evaluate_all()
        with self.assertRaisesRegex(CommercialError, "fim da carência"):
            e.schedule_suspension(self.actor, sid, self.pc.clock.wall + timedelta(days=1), "x", operational_ack=True)
        at = self.pc.clock.wall + timedelta(days=10)
        with self.assertRaisesRegex(CommercialError, "requisitos operacionais"):
            e.schedule_suspension(self.actor, sid, at, "inadimplência", operational_ack=False)
        with self.assertRaisesRegex(CommercialError, "confirmação de um administrador"):
            e.schedule_suspension(self.lm.actor(self.fin), sid, at, "inadimplência", operational_ack=True)
        with self.assertRaisesRegex(CommercialError, "Confirmação recusada"):
            e.schedule_suspension(self.lm.actor(self.fin), sid, at, "inadimplência", operational_ack=True,
                                  confirmed_by=("admin", "senha-errada"))
        s = e.schedule_suspension(self.lm.actor(self.fin), sid, at, "inadimplência", operational_ack=True,
                                  confirmed_by=("admin", "Senha-Forte-123"))
        self.assertEqual(s["state"], "suspension_scheduled")
        self.client.svc.import_authorization(self.auth_file(lid), actor="admin")
        st = self.st()
        self.assertEqual((st.state, st.commercial), (LicenseState.VALID, "suspension_scheduled"))
        self.assertIn("Suspensão programada", st.warning)
        e.edit(self.actor, sid, contract_allows_suspension=False)
        with self.assertRaisesRegex(CommercialError, "contrato"):
            e.suspend_now(self.actor, sid, "x", operational_ack=True)

    def test_c05_permanent_license_is_never_suspended_for_fees(self):
        lic, st = self.activate("permanent")
        s = self.sub(lic["license_id"])
        self.assertEqual(s["state"], "active")
        with self.assertRaisesRegex(CommercialError, "permanente"):
            self.lm.commercial.suspend_now(self.actor, s["id"], "manutenção não paga", operational_ack=True)
        self.pc.clock.advance(days=900)
        self.assertEqual(self.st().state, LicenseState.VALID)

    def test_c06_effective_suspension(self):
        lic, _ = self.activate()
        lid = lic["license_id"]
        self.overdue_and_suspend(lid, schedule=True)
        self.client.svc.import_authorization(self.auth_file(lid), actor="admin")
        self.assertTrue(self.client.svc.allows("storage"))
        self.pc.clock.advance(days=2, hours=1)                    # a data chega sem nenhum contato
        st = self.st()
        self.assertEqual((st.state, st.commercial), (LicenseState.COMMERCIAL_SUSPENDED, "suspended"))
        self.assertFalse(self.client.svc.allows("storage"))
        self.assertFalse(self.client.svc.allows("printing"))
        self.assertIsNotNone(st.restricted_since)
        self.assertEqual(self.client.svc.drain_cutoff(), st.restricted_since + timedelta(seconds=1))
        reason = self.client.svc.suspension_reason()
        self.assertIn("preservados", reason)
        self.assertNotIn("R$", reason)
        self.assertNotIn("mensalidade", reason.lower())         # texto neutro para a recepção
        self.assertIn("preservad", self.client.svc.policy_text())


# ============================================================================ 7–14: reativação, conectividade e cobrança
class OnlineBase(Base):
    def setUp(self):
        super().setUp()
        from license_server.core import ServerCore, SessionUser
        from license_server.http import LicenseHTTPServer, certificate_pin, ensure_certificate
        self.srv_key = crypto.generate_ed25519()
        self.client_keys = {**self.keys, "srv-teste": crypto.public_hex(self.srv_key)}
        self.scopes = {"srv-teste": ("authorization",)}
        self._client_keys()
        self.core = ServerCore(self.tmp / "srv", signer=("srv-teste", self.srv_key), license_keys=self.keys,
                               clock=lambda: self.pc.clock.wall, webhook_secret="segredo-do-webhook-123")
        self.addCleanup(self.core.close)
        self.core.create_user(None, "comercial", "Comercial", "admin", "Comercial-Senha-1")
        r = self.core.db.conn().execute("SELECT id FROM users WHERE username = 'comercial'").fetchone()
        self.by = SessionUser(r["id"], "comercial", "Comercial", "admin")
        cert, key = ensure_certificate(self.tmp / "tls", ["127.0.0.1"])
        self.pin = certificate_pin(cert)
        self.http = LicenseHTTPServer(("127.0.0.1", 0), self.core, cert=cert, key=key)
        self.srv_port = self.http.server_address[1]
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)
        self.lm.commercial.set_settings(self.actor, {"server_url": f"https://127.0.0.1:{self.srv_port}",
                                                     "server_pin": self.pin})

    def _client_keys(self):
        self.client.svc.public_keys = self.client_keys
        self.client.svc.key_scopes = self.scopes

    def reopen(self):
        self.client.reopen(self.client_keys)
        self._client_keys()

    def activate_online(self, ltype="monthly"):
        lic, st = self.activate(ltype, validation="online")
        self.core.register_license(self.by, lic["document"], price_cents=49900)
        return lic, st

    def server_sub(self, lid):
        return self.core.engine.subscription(lid)

    def check(self):
        return self.client.svc.check_online(actor="serviço")


class ReactivationTest(OnlineBase):
    def test_c07_online_reactivation(self):
        lic, st = self.activate_online()
        lid = lic["license_id"]
        self.assertEqual(st.validation, "online")
        self.assertEqual(self.check().result, "ok")
        self.assertEqual(self.st().connectivity, "ok")
        e = self.core.engine
        sid = self.server_sub(lid)["id"]
        self.at_due(lid, timedelta(days=2))
        e.evaluate_all()
        self.at_due(lid, timedelta(days=8))
        e.suspend_now(Actor("comercial", "admin"), sid, "inadimplência", operational_ack=True)
        self.assertEqual(self.check().result, "ok")
        st = self.st()
        self.assertEqual((st.state, st.commercial), (LicenseState.COMMERCIAL_SUSPENDED, "suspended"))
        r = self.core.action(self.by, sid, "payment", {"reference": "PIX-E2E-0001", "periods": 1,
                                                       "amount_cents": 49900})
        self.assertTrue(r["reactivated"])
        self.assertEqual(self.check().result, "ok")
        st = self.st()
        self.assertEqual((st.state, st.commercial), (LicenseState.VALID, "reactivated"))
        ev = [x for x in self.client.events.query(__import__("app.database.repositories.events_repo",
                                                             fromlist=["EventFilter"]).EventFilter(limit=200))
              if x.action == "license.reactivated"]
        self.assertTrue(ev and "License Server" in ev[0].message and "license-server" in ev[0].message)
        hist = self.client.svc.state_history()
        self.assertTrue(any(h["kind"] == "license" and h["detail"] == "reativação" for h in hist))

    def test_c08_offline_reactivation(self):
        lic, _ = self.activate()
        lid = lic["license_id"]
        self.overdue_and_suspend(lid)
        self.client.svc.import_authorization(self.auth_file(lid), actor="admin")
        self.assertEqual(self.st().state, LicenseState.COMMERCIAL_SUSPENDED)
        r = self.lm.commercial.confirm_payment(self.lm.actor(self.fin), self.sub(lid)["id"], reference="BOL-778899",
                                               source="manual", periods=1, amount_cents=49900)
        self.assertTrue(r["reactivated"])
        st = self.client.svc.import_authorization(self.auth_file(lid), actor="administrador da clínica")
        self.assertEqual((st.state, st.commercial), (LicenseState.VALID, "reactivated"))
        row = self.client.db.connection().execute(
            "SELECT source, channel, applied_by, issued_by FROM license_authorizations ORDER BY id DESC").fetchone()
        self.assertEqual(tuple(row), ("manager", "offline", "administrador da clínica", "admin"))
        hist = self.lm.commercial.reactivations(self.sub(lid)["id"])
        self.assertEqual(hist[0]["actor"], "fin")
        self.assertEqual(hist[0]["reason"], "pagamento confirmado")


class ConnectivityTest(OnlineBase):
    def test_c09_no_internet_is_not_default(self):
        lic, _ = self.activate_online()
        self.assertEqual(self.check().result, "ok")
        self.client.settings["licensing.server_url_override"] = "https://licencas-vyonix.invalid:8743"
        r = self.check()
        self.assertEqual(r.result, "no_internet")
        st = self.st()
        self.assertEqual((st.state, st.connectivity), (LicenseState.VALID, "no_internet"))
        self.pc.clock.advance(days=8)                              # autorização online (7 dias) vencida
        st = self.st()
        self.assertEqual(st.state, LicenseState.VALID)                # tolerância de 10 dias
        self.assertIn("Tolerância", st.warning)
        self.pc.clock.advance(days=10)
        st = self.st()
        self.assertEqual(st.state, LicenseState.AUTH_EXPIRED)
        self.assertIn("não indica inadimplência", st.message)
        self.assertEqual(st.commercial, "active")                  # situação financeira separada
        self.client.settings["licensing.server_url_override"] = ""
        self.assertEqual(self.check().result, "ok")                 # internet volta: libera na hora
        self.assertEqual(self.st().state, LicenseState.VALID)

    def test_c10_license_server_unavailable(self):
        from tests.dicom_helpers import free_port
        self.activate_online()
        self.client.settings["licensing.server_url_override"] = f"https://127.0.0.1:{free_port()}"
        r = self.check()
        self.assertEqual(r.result, "server_unavailable")
        st = self.st()
        self.assertEqual((st.state, st.connectivity), (LicenseState.VALID, "server_unavailable"))
        kinds = [h["to_state"] for h in self.client.svc.state_history() if h["kind"] == "connectivity"]
        self.assertIn("server_unavailable", kinds)


class BillingTest(OnlineBase):
    def setUp(self):
        super().setUp()
        from tests.inter_fake import FakeInter
        from vyonix_commercial.billing.inter import InterConfig, InterProvider
        self.bank = FakeInter(self.tmp / "inter")
        self.addCleanup(self.bank.close)
        self.core.provider = InterProvider(InterConfig(
            client_id=self.bank.client_id, client_secret=self.bank.client_secret, cert_file=str(self.bank.client_cert),
            key_file=str(self.bank.client_key), base_url=self.bank.base_url, ca_file=str(self.bank.server_cert)))
        self.lic, _ = self.activate_online()
        self.sid = self.server_sub(self.lic["license_id"])["id"]
        self.paid_before = self.server_sub(self.lic["license_id"])["paid_until"]

    def charge(self):
        return self.core.action(self.by, self.sid, "charge", {"due_date": "2026-11-01", "payer_document":
                                                               "12345678000190", "payer_address": {
                                                                   "endereco": "Rua A, 1", "cidade": "Recife",
                                                                   "uf": "PE", "cep": "50000000"}})

    def hook(self, body, secret="segredo-do-webhook-123"):
        return self.core.webhook("inter", secret, body, "200.1.2.3")

    def test_c11_payment_confirmed(self):
        ch = self.charge()
        self.assertEqual(ch["status"], "issued")
        self.bank.pay(ch["provider_ref"], 499.0)
        out = self.hook(self.bank.webhook_body(ch["provider_ref"], "RECEBIDO"))
        self.assertIn("pagamento confirmado", out["processed"][0]["result"])
        s = self.server_sub(self.lic["license_id"])
        self.assertGreater(s["paid_until"], self.paid_before)
        self.assertEqual(s["last_payment_cents"], 49900)
        self.assertIn(("GET", f"/cobranca/v3/cobrancas/{ch['provider_ref']}"), self.bank.calls)   # consulta ao banco
        self.assertEqual(self.check().result, "ok")
        self.assertEqual(self.client.svc.authorizations.current(self.lic["license_id"])["commercial"]["paid_until"],
                         s["paid_until"])

    def test_c12_boleto_issued_but_not_paid(self):
        ch = self.charge()
        out = self.hook(self.bank.webhook_body(ch["provider_ref"], "RECEBIDO"))     # aviso falso ou adiantado
        self.assertIn("consultada: issued", out["processed"][0]["result"])
        self.assertEqual(self.server_sub(self.lic["license_id"])["paid_until"], self.paid_before)
        self.core.engine.register_payment_claim(Actor("fin", "financial"), self.sid, "cliente enviou comprovante")
        self.assertEqual(self.server_sub(self.lic["license_id"])["paid_until"], self.paid_before)
        self.bank.pay(ch["provider_ref"], 499.0, status="MARCADO_RECEBIDO")         # baixa manual: conferir
        self.hook(self.bank.webhook_body(ch["provider_ref"], "MARCADO_RECEBIDO"))
        self.assertEqual(self.core.engine.charges(self.sid)[0]["status"], "manual_check")
        self.assertEqual(self.server_sub(self.lic["license_id"])["paid_until"], self.paid_before)

    def test_c13_duplicate_bank_notification(self):
        ch = self.charge()
        self.bank.pay(ch["provider_ref"], 499.0)
        body = self.bank.webhook_body(ch["provider_ref"], "RECEBIDO")
        self.hook(body)
        after = self.server_sub(self.lic["license_id"])["paid_until"]
        out = self.hook(body)
        self.assertEqual(out["processed"][0]["result"], "repetida (ignorada)")
        self.assertEqual(self.server_sub(self.lic["license_id"])["paid_until"], after)
        self.assertEqual(len(self.core.engine.payments(self.sid)), 1)
        r = self.core.engine.confirm_payment(Actor("fin", "financial"), self.sid, reference=f"inter:{ch['provider_ref']}",
                                             source="manual")
        self.assertTrue(r["duplicate"])
        from license_server.core import ServerError
        with self.assertRaises(ServerError) as cm:
            self.hook(body, secret="segredo-errado-000000")
        self.assertEqual(cm.exception.status, 404)


class ReplayAndTamperTest(OnlineBase):
    def test_c14_reuse_of_old_authorization(self):
        lic, _ = self.activate()
        lid = lic["license_id"]
        a1 = self.auth_file(lid)
        self.pc.clock.advance(seconds=5)
        a2 = self.auth_file(lid)
        self.client.svc.import_authorization(a1, actor="t")
        self.client.svc.import_authorization(a2, actor="t")
        with self.assertRaisesRegex(ValidationError, "mais antiga"):
            self.client.svc.import_authorization(a1, actor="t")
        with self.assertRaisesRegex(ValidationError, "já foi aplicada|mais antiga"):
            self.client.svc.import_authorization(a2, actor="t")

    def test_c14_online_replay_rejected(self):
        lic, _ = self.activate_online()
        captured = {}
        from app.licensing.online import _post as real_post

        def spy(url, body, **kw):
            status, data = real_post(url, body, **kw)
            captured["resp"], captured["body"] = data, body
            return status, data
        self.assertEqual(self.client.svc.check_online(actor="t", post=spy).result, "ok")
        old = json.loads(captured["resp"])["authorization"]
        with self.assertRaisesRegex(ValidationError, "não corresponde a esta consulta|mais antiga|já foi aplicada"):
            self.client.svc.apply_authorization(old, actor="t", source="online", expected_nonce="f" * 32)
        with self.assertRaisesRegex(ValidationError, "consulta deste computador"):
            self.client.svc.import_authorization(old, actor="t")        # resposta online usada como arquivo
        replay = lambda url, body, **kw: (200, captured["resp"])  # noqa: E731 - resposta antiga reenviada
        r = self.client.svc.check_online(actor="t", post=replay)
        self.assertEqual(r.result, "invalid_response")
        self.assertEqual(self.st().state, LicenseState.VALID)          # suspeita registrada; nada é suspenso
        from license_server.core import ServerError
        with self.assertRaises(ServerError) as cm:                   # o servidor também recusa o número repetido
            self.core.authorize(captured["body"], "10.0.0.5")
        self.assertEqual(cm.exception.status, 409)

    def test_c15_tampered_license_and_authorization(self):
        lic, _ = self.activate()
        lid = lic["license_id"]
        doc = json.loads(self.auth_file(lid))
        from vyonix_protocol.codec import b64d, b64e
        p = json.loads(b64d(doc["payload"]))
        p["commercial"]["paid_until"] = "2099-12-31T23:59:59Z"
        doc["payload"] = b64e(json.dumps(p).encode())
        with self.assertRaisesRegex(ValidationError, "Assinatura digital inválida"):
            self.client.svc.import_authorization(json.dumps(doc), actor="t")
        ldoc = json.loads(lic["document"])
        lp = json.loads(b64d(ldoc["payload"]))
        lp["type"] = "permanent"
        ldoc["payload"] = b64e(json.dumps(lp).encode())
        self.assertEqual(self.client.svc.check(json.dumps(ldoc)).status.state, LicenseState.INVALID)
        # chave do servidor (escopo "authorization") não emite licença
        forged = F.build_signed(F.LICENSE_FORMAT, lp, "srv-teste", self.srv_key.sign)
        st = self.client.svc.check(forged).status
        self.assertEqual(st.state, LicenseState.INVALID)
        self.assertIn("não está autorizada", st.message)
        # cópia do cofre alterada fora do VYONIX: suspensão por integridade (revalidação administrativa)
        self.client.svc.import_authorization(self.auth_file(lid), actor="t")
        raw = json.loads(self.pc.file_backend.get("authorization"))
        raw["r"]["items"][lid]["payload"]["commercial"]["paid_until"] = "2099-12-31T23:59:59Z"
        self.pc.file_backend.put("authorization", json.dumps(raw))
        self.assertEqual(self.st().state, LicenseState.SUSPENDED)

    def test_c16_clock_change(self):
        lic, _ = self.activate()
        lid = lic["license_id"]
        self.overdue_and_suspend(lid)
        self.client.svc.import_authorization(self.auth_file(lid), actor="t")
        self.assertEqual(self.st().state, LicenseState.COMMERCIAL_SUSPENDED)
        self.pc.clock.shift_wall(days=-60)                             # volta o relógio do Windows
        self.assertFalse(self.st().active)
        self.client.reopen(self.keys)
        self.assertFalse(self.st().active)
        self.pc.clock.shift_wall(days=60)
        self.assertEqual(self.st().state, LicenseState.COMMERCIAL_SUSPENDED)


# ============================================================================ 17–20: instalação e hardware
class InstallationTest(OnlineBase):
    def test_c17_reinstall(self):
        from app.licensing.installation import InstallationManager
        lic, _ = self.activate_online()
        lid = lic["license_id"]
        old_sub = self.sub(lid)
        a = self.auth_file(lid)
        self.client.svc.end_activation("desinstalação")
        mgr = InstallationManager(self.pc.vault())
        mgr.uninstall()
        mgr.provision("fresh", legacy_id=None)
        self.reopen()
        self.assertEqual(self.st().state, LicenseState.NOT_ACTIVATED)
        with self.assertRaisesRegex(ValidationError, "outra instalação"):
            self.client.svc.install(lic["document"], actor="t")
        from license_server.core import ServerError
        with self.assertRaises(ServerError) as cm:
            self.core.authorize({"product_id": F.PRODUCT_ID, "license_id": lid, "nonce": "a" * 32,
                                 "installation_id": self.client.svc.installation_id(),
                                 "hardware_id": self.client.svc.hardware_id()}, "10.0.0.9")
        self.assertEqual(cm.exception.status, 403)
        info = self.lm.import_request(self.admin, self.client.svc.request_code(reason="reinstall"))
        new = self.lm.reactivate(self.admin, lid, info.request_id, "reinstall", "Windows reinstalado")
        self.client.svc.install(new["document"], actor="t")
        s = self.sub(new["license_id"])
        self.assertEqual((s["id"], s["paid_until"]), (old_sub["id"], old_sub["paid_until"]))   # mesma assinatura
        with self.assertRaisesRegex(ValidationError, "outra licença"):
            self.client.svc.import_authorization(a, actor="t")
        self.core.register_license(self.by, new["document"])
        self.assertEqual(self.check().result, "ok")
        self.assertEqual(self.core.licenses()[-1]["status"], "replaced")

    def test_c18_official_update(self):
        from app.database.migrations import MIGRATIONS
        from app.database.migrator import migrate
        from app.licensing.installation import InstallationManager
        lic, _ = self.activate_online()
        self.assertEqual(self.check().result, "ok")
        inst = self.client.svc.installation_id()
        auth = self.client.svc.authorizations.current(lic["license_id"])
        InstallationManager(self.pc.vault()).provision("upgrade", legacy_id=None)
        migrate(self.client.db, MIGRATIONS, backup_dir=self.tmp / "bk2")
        self.reopen()
        st = self.st()
        self.assertEqual((st.state, st.license_id), (LicenseState.VALID, lic["license_id"]))
        self.assertEqual(self.client.svc.installation_id(), inst)
        self.assertEqual(self.client.svc.authorizations.current(lic["license_id"]), auth)
        self.assertEqual(self.client.svc.authorizations.online()["result"], "ok")

    def test_c19_legitimate_hardware_change(self):
        lic, _ = self.activate()
        lid = lic["license_id"]
        self.pc.mac = ["00:11:22:33:44:55", *self.pc.mac]              # placa de rede adicional
        self.client.svc.profile(refresh=True)
        self.assertEqual(self.st().state, LicenseState.VALID)
        self.pc.disk = "SSD-NOVO-9999"                                  # troca de disco
        self.client.svc.profile(refresh=True)
        self.assertEqual(self.st().state, LicenseState.HARDWARE_MISMATCH)
        info = self.lm.import_request(self.admin, self.client.svc.request_code(reason="disk"))
        new = self.lm.reactivate(self.admin, lid, info.request_id, "disk", "SSD substituído pela assistência")
        self.assertEqual(self.client.svc.install(new["document"], actor="t").state, LicenseState.VALID)
        s = self.sub(new["license_id"])
        self.assertEqual(s["hardware_id"], new["hardware_id"])
        self.assertTrue(any(h["action"] == "relink" for h in self.lm.commercial.history(s["id"])))

    def test_c20_copy_to_another_computer(self):
        lic, _ = self.activate_online()
        self.assertEqual(self.check().result, "ok")
        other = Computer(uuid="11111111-2222-3333-4444-555555555555", board="ASUS|PRIME|X1",
                         system="0000aaaa-bbbb", disk="OUTRO-DISCO", mac=["AA:BB:CC:DD:EE:FF"])
        other.db_backend, other.file_backend, other.reg_backend = (self.pc.db_backend, self.pc.file_backend,
                                                                   self.pc.reg_backend)
        other.seal_key = self.pc.seal_key                               # cópia completa do disco
        copy = Client(other, self.tmp / "c1", self.client_keys)
        copy.svc.key_scopes = self.scopes
        self.addCleanup(copy.close)
        st = copy.svc.status(refresh=True)
        self.assertEqual(st.state, LicenseState.HARDWARE_MISMATCH)
        from license_server.core import ServerError
        with self.assertRaises(ServerError) as cm:
            self.core.authorize({"product_id": F.PRODUCT_ID, "license_id": lic["license_id"], "nonce": "b" * 32,
                                 "installation_id": copy.svc.installation_id(),
                                 "hardware_id": copy.svc.hardware_id()}, "10.0.0.8")
        self.assertEqual(cm.exception.status, 403)


# ============================================================================ 21–28: aplicativo completo
@unittest.skipUnless(HAS_NET, "pydicom/pynetdicom não instalados")
class FullAppTest(TempDirTestCase):
    STUDY = "1.2.826.0.1.3680043.8.498.91"

    def setUp(self):
        super().setUp()
        from app.bootstrap import bootstrap
        from app.printing.backends.pdf import PDF_PRINTER
        from tests.dicom_helpers import free_port
        self.port = free_port()
        os.environ["VYONIX_LICENSE_ENFORCE"] = "1"
        try:
            self.ctx = bootstrap(data_dir=self.tmp / "data")
        finally:
            os.environ["VYONIX_LICENSE_ENFORCE"] = "0"
        self.addCleanup(lambda: self.ctx.close())
        self.lm, self.admin, self.keys, self.cid = make_manager(self.tmp / "lm")
        self.addCleanup(self.lm.close)
        self.ctx.license.public_keys = self.keys
        self.actor = self.lm.actor(self.admin)
        info = self.lm.import_request(self.admin, self.ctx.license.request_code())
        self.lic = self.lm.issue(self.admin, info.request_id, self.cid, ltype="monthly", edition="Profissional")
        self.lid = self.lic["license_id"]
        self.assertEqual(self.ctx.license.install(self.lic["document"], actor="t").state, LicenseState.VALID)
        self.ctx.settings.update({"dicom.storage.bind_address": "127.0.0.1", "dicom.storage.port": self.port,
                                  "jobs.collect_seconds": 2}, actor="t")
        self.auto = self.ctx.devices.create({"name": "CT automática", "called_ae": "VYONIX_AUTO", "modality": "CT"},
                                            actor="t", authorized=True)
        self.ctx.device_settings.save(self.auto.id, {"printer": PDF_PRINTER, "auto_print": True}, actor="t")
        self.demand = self.ctx.devices.create({"name": "CR recepção", "called_ae": "VYONIX_CR", "modality": "CR"},
                                              actor="t", authorized=True)
        self.ctx.device_settings.save(self.demand.id, {"printer": PDF_PRINTER, "auto_print": False}, actor="t")
        self.ctx.storage_scp.start()

    def send(self, called, n=2, study=None):
        from app.dicom import scu
        from tests.dicom_helpers import make_ct
        study = study or f"{self.STUDY}.{uuid.uuid4().int % 10 ** 8}"
        files = [make_ct(self.tmp / f"in-{uuid.uuid4().hex}.dcm", study_uid=study, series_uid=study + ".1",
                         value=400 + i, patient_name="SOUZA^ANA", AccessionNumber="ACC9") for i in range(n)]
        return scu.store_files("127.0.0.1", self.port, called, files, calling_ae="EQUIP")

    def suspend(self):
        """Inadimplência confirmada (avisos + fim da carência) e suspensão aplicada pelo License Manager."""
        now = datetime.now(timezone.utc)
        c = self.lm.db.conn()
        c.execute("UPDATE com_subscriptions SET paid_until = ?, grace_days = 5 WHERE license_id = ?",
                  (iso(now - timedelta(days=2)), self.lid))
        self.lm.commercial.evaluate_all()                                   # aviso de atraso registrado
        c.execute("UPDATE com_subscriptions SET grace_days = 1 WHERE license_id = ?", (self.lid,))
        sid = self.lm.commercial.subscription(self.lid)["id"]
        self.lm.commercial.suspend_now(self.actor, sid, "inadimplência confirmada", operational_ack=True)
        st = self.ctx.license.import_authorization(self.lm.offline_authorization(self.admin, self.lid)["document"],
                                                   actor="t")
        self.assertEqual(st.state, LicenseState.COMMERCIAL_SUSPENDED)
        return st

    def reactivate(self):
        sid = self.lm.commercial.subscription(self.lid)["id"]
        self.lm.commercial.confirm_payment(self.actor, sid, reference=f"PG-{uuid.uuid4().hex[:8]}", source="manual",
                                           periods=2)
        st = self.ctx.license.import_authorization(self.lm.offline_authorization(self.admin, self.lid)["document"],
                                                   actor="t")
        self.assertTrue(st.active)
        return st

    def files(self):
        return {r["sop_instance_uid"]: (r["file_path"], r["file_sha256"]) for r in self.ctx.db.connection().execute(
            "SELECT sop_instance_uid, file_path, file_sha256 FROM instances")}

    def test_c21_images_preserved(self):
        import hashlib
        from pathlib import Path
        from app.imaging import tone
        self.assertEqual(self.send("VYONIX_CR"), [0, 0])
        self.ctx.device_settings.save_tone(self.demand.id, tone.ToneControls(brightness=1.0, gamma=0.5), actor="t",
                                           reason="calibração")
        before = self.files()
        cal = self.ctx.device_settings.get(self.demand.id)
        self.suspend()
        self.reactivate()
        after = self.files()
        self.assertEqual(before, after)
        for path, sha in after.values():
            self.assertEqual(hashlib.sha256(Path(path).read_bytes()).hexdigest(), sha)   # nada alterado/cifrado
        self.assertEqual(self.ctx.device_settings.get(self.demand.id), cal)

    def test_c22_export_during_suspension(self):
        self.send("VYONIX_CR", n=3)
        self.suspend()
        out = self.tmp / "exportacao"
        out.mkdir()
        res = self.ctx.exporter.export(out, actor="admin")
        self.assertEqual((res.files, res.studies, res.mismatched), (3, 1, []))
        manifest = (res.folder / "manifesto.csv").read_text(encoding="utf-8")
        self.assertNotIn("SOUZA", manifest)                                # manifesto sem nome de paciente
        self.assertEqual(manifest.count("\n"), 4)

    def test_c23_jobs_in_progress_at_suspension(self):
        from app.jobs.states import JobState
        self.send("VYONIX_AUTO", n=2)
        accepted = self.ctx.worker.collector.flush(force=True)
        self.assertEqual(len(accepted), 1)
        self.suspend()
        self.assertIsNotNone(self.ctx.worker.suspended())
        job = self.ctx.worker._next_job()                                  # aceito antes: concluído
        self.assertEqual(job.id, accepted[0])
        self.ctx.worker.process(job)
        self.assertIn(self.ctx.jobs.get_job(job.id).state, (JobState.SPOOLED, JobState.COMPLETED))
        with self.assertRaises(ConnectionError):                           # nova recepção recusada
            self.send("VYONIX_AUTO", n=1)
        if True:                                                           # trabalho criado após a suspensão
            c = self.ctx.db.connection()
            r = c.execute("SELECT * FROM jobs WHERE id = ?", (accepted[0],)).fetchone()
            cols = [k for k in r.keys() if k not in ("id", "uuid", "idempotency_key", "state", "created_at",
                                                    "updated_at")]
            now = (datetime.now(timezone.utc) + timedelta(seconds=3)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            c.execute(f"INSERT INTO jobs(uuid, idempotency_key, state, created_at, updated_at, {', '.join(cols)}) "
                      f"VALUES (?, ?, 'received', ?, ?, {', '.join('?' * len(cols))})",
                      (uuid.uuid4().hex, uuid.uuid4().hex, now, now, *[r[k] for k in cols]))
            later = c.execute("SELECT MAX(id) FROM jobs").fetchone()[0]
        self.assertIsNone(self.ctx.worker._next_job())                     # aguarda na fila, nada apagado
        self.assertEqual(self.ctx.jobs.get_job(later).state, JobState.RECEIVED)
        self.reactivate()
        self.assertEqual(self.ctx.worker._next_job().id, later)

    def test_c24_recovery_after_restart(self):
        from app.bootstrap import bootstrap
        self.suspend()
        self.ctx.close()
        os.environ["VYONIX_LICENSE_ENFORCE"] = "1"
        try:
            self.ctx = bootstrap(data_dir=self.tmp / "data")
        finally:
            os.environ["VYONIX_LICENSE_ENFORCE"] = "0"
        self.ctx.license.public_keys = self.keys
        st = self.ctx.license.status(refresh=True)
        self.assertEqual((st.state, st.commercial), (LicenseState.COMMERCIAL_SUSPENDED, "suspended"))
        self.assertEqual(self.ctx.devices.get(self.auto.id).called_ae, "VYONIX_AUTO")
        self.reactivate()
        hist = [(h["kind"], h["to_state"]) for h in self.ctx.license.state_history()]
        self.assertIn(("commercial", "suspended"), hist)
        self.assertIn(("commercial", "reactivated"), hist)

    def test_c25_dicom_rules_compatibility(self):
        from app.dicom import scu
        self.assertTrue(scu.echo("127.0.0.1", self.port, "VYONIX_AUTO", calling_ae="EQUIP")["ok"])
        self.suspend()
        self.assertFalse(scu.echo("127.0.0.1", self.port, "VYONIX_AUTO", calling_ae="EQUIP")["ok"])
        self.assertIn("SUSPENSO", self.ctx.storage_scp.status().detail)
        self.reactivate()
        self.assertTrue(scu.echo("127.0.0.1", self.port, "VYONIX_AUTO", calling_ae="EQUIP")["ok"])
        d = self.ctx.devices.get(self.auto.id)
        self.assertEqual((d.called_ae, d.enabled if hasattr(d, "enabled") else True), ("VYONIX_AUTO", True))

    def test_c26_automatic_printing(self):
        from app.jobs.states import JobState
        self.assertEqual(self.send("VYONIX_AUTO"), [0, 0])
        jobs = self.ctx.worker.collector.flush(force=True)
        self.ctx.worker.process(self.ctx.worker._next_job())
        self.assertIn(self.ctx.jobs.get_job(jobs[0]).state, (JobState.SPOOLED, JobState.COMPLETED))

    def test_c27_on_demand_printing(self):
        from app.security.users import UserService  # noqa: F401
        self.send("VYONIX_CR", n=1)
        self.ctx.worker.collector.flush(force=True)
        self.ctx.users.create("recep", "Recepção", "receptionist", "Recep1234", actor="t", must_change=False)
        user = self.ctx.users.authenticate("recep", "Recep1234")
        e = self.ctx.exams.search()["exams"][0]
        self.assertEqual(e["print_state"], "available")
        self.suspend()
        with self.assertRaises(ValidationError) as cm:
            self.ctx.exams.print_exam(e["id"], user, request_key=str(uuid.uuid4()))
        self.assertIn("indisponível", str(cm.exception))
        self.assertNotIn("R$", str(cm.exception))
        self.reactivate()
        r = self.ctx.exams.print_exam(e["id"], user, request_key=str(uuid.uuid4()))
        self.assertTrue(r.get("job_id") or r.get("jobs") or r)

    def test_c28_pickup_control(self):
        self.send("VYONIX_CR", n=1)
        self.ctx.worker.collector.flush(force=True)
        self.ctx.users.create("recep", "Recepção", "receptionist", "Recep1234", actor="t", must_change=False)
        user = self.ctx.users.authenticate("recep", "Recep1234")
        e = self.ctx.exams.search()["exams"][0]
        self.suspend()                                                     # entrega continua registrável
        self.ctx.exams.set_pickup(e["id"], user, "pronto")
        self.ctx.exams.set_pickup(e["id"], user, "entregue", delivered_to="Ana (RG 9)")
        got = self.ctx.exams.get(e["id"])
        self.assertEqual((got["pickup_state"], got["delivered_to"]), ("entregue", "Ana (RG 9)"))


# ============================================================================ 29–30: auditoria e APIs
class AuditAndApiTest(OnlineBase):
    def test_c29_administrative_audit(self):
        lic, _ = self.activate()
        lid = lic["license_id"]
        sid = self.sub(lid)["id"]
        self.at_due(lid, timedelta(days=2))
        self.lm.commercial.evaluate_all()
        self.lm.commercial.grant_grace(self.lm.actor(self.fin), sid, 3, "negociação")
        self.at_due(lid, timedelta(days=11))
        self.lm.commercial.suspend_now(self.actor, sid, "inadimplência confirmada", operational_ack=True)
        self.lm.commercial.reactivate(self.lm.actor(self.fin), sid, "acordo assinado",
                                      extend_until=self.pc.clock.wall + timedelta(days=10),
                                      confirmed_by=("admin", "Senha-Forte-123"))
        self.lm.offline_authorization(self.admin, lid)
        actions = [a["action"] for a in self.lm.audit_log(200)]
        for a in ("license.issue", "commercial.create", "commercial.grace", "commercial.suspend",
                  "commercial.reactivate", "commercial.authorization"):
            self.assertIn(a, actions)
        self.assertEqual(self.lm.verify_audit(), [])
        react = [a for a in self.lm.audit_log(200) if a["action"] == "commercial.reactivate"][0]
        self.assertEqual(react["actor"], "fin")
        self.assertIn("admin", react["details"])                          # quem confirmou
        hist = [(h["action"], h["actor"]) for h in self.lm.commercial.history(sid)]
        self.assertIn(("suspend", "admin"), hist)
        self.assertIn(("reactivate", "fin"), hist)
        self.lm.db.conn().execute("UPDATE audit SET actor = 'outro' WHERE action = 'commercial.suspend'")
        self.assertNotEqual(self.lm.verify_audit(), [])                  # alteração fora do aplicativo detectada

    def test_c30_api_security(self):
        import http.client
        import ssl
        from app.licensing.online import REQUEST_FIELDS
        lic, _ = self.activate_online()
        sent = {}

        def spy(url, body, **kw):
            from app.licensing.online import _post
            sent.update(body)
            return _post(url, body, **kw)
        self.assertEqual(self.client.svc.check_online(actor="t", post=spy).result, "ok")
        self.assertEqual(sorted(sent), sorted(REQUEST_FIELDS))           # nenhum dado clínico enviado
        self.assertFalse({"patient_name", "patient_id", "study_uid"} & set(sent))

        def call(method, path, body=None, token=None):
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            c = http.client.HTTPSConnection("127.0.0.1", self.srv_port, timeout=10, context=ctx)
            h = {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}
            c.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=h)
            r = c.getresponse()
            out = (r.status, json.loads(r.read() or b"{}"))
            c.close()
            return out
        self.assertEqual(call("GET", "/v1/admin/subscriptions")[0], 401)
        self.assertEqual(call("GET", "/v1/admin/subscriptions", token="token-falso")[0], 401)
        self.core.create_user(self.by, "consulta", "Consulta", "viewer", "Consulta-Senha-1")
        code, login = call("POST", "/v1/admin/login", {"username": "consulta", "password": "Consulta-Senha-1"})
        self.assertEqual(code, 200)
        tok = login["token"]
        sid = self.server_sub(lic["license_id"])["id"]
        self.assertEqual(call("GET", "/v1/admin/subscriptions", token=tok)[0], 200)
        code, err = call("POST", f"/v1/admin/subscriptions/{sid}/payment", {"reference": "X"}, token=tok)
        self.assertEqual(code, 403)                                       # perfil sem permissão de pagamento
        self.assertIn("Consulta", err["error"])
        bad = {**sent, "nonce": "c" * 32, "patient_name": "SILVA^MARIA"}
        self.assertEqual(call("POST", "/v1/authorize", bad)[0], 400)       # campos não previstos recusados
        for _ in range(10):
            call("POST", "/v1/admin/login", {"username": "consulta", "password": "errada"})
        self.assertEqual(call("POST", "/v1/admin/login", {"username": "consulta", "password": "errada"})[0], 429)
        plain = http.client.HTTPConnection("127.0.0.1", self.srv_port, timeout=5)   # sem TLS: não atende
        with self.assertRaises(Exception):
            plain.request("GET", "/v1/health")
            plain.getresponse().read()
        plain.close()
        self.http.admin_networks = [__import__("ipaddress").ip_network("10.0.0.0/8")]
        self.assertEqual(call("GET", "/v1/admin/subscriptions", token=tok)[0], 403)   # rede não autorizada


class ManagerUpgradeTest(TempDirTestCase):
    def test_license_manager_database_upgrade_keeps_users(self):
        """License Manager da revisão anterior (esquema 1) → Gestão Comercial sem perder usuários."""
        import sqlite3
        from license_manager.db import MIGRATIONS, _statements
        from license_manager.paths import LMPaths
        from license_manager.service import LicenseManager
        folder = self.tmp / "lm-antigo"
        folder.mkdir()
        c = sqlite3.connect(folder / "license_manager.db")
        for stmt in _statements(MIGRATIONS[0][1]):
            c.execute(stmt)
        c.execute("PRAGMA user_version = 1")
        c.execute("INSERT INTO users(username, display_name, role, pw_hash, created_at) VALUES "
                  "('emissor', 'Emissor', 'issuer', 'x', '2026-01-01')")
        c.commit()
        c.close()
        lm = LicenseManager(LMPaths(folder, "custom"))
        self.addCleanup(lm.close)
        self.assertEqual(lm.applied, [2])
        self.assertEqual([u["role"] for u in lm.users()], ["issuer"])
        self.assertEqual(lm.commercial.settings()["grace_days"], "7")
        self.assertEqual(len(lm.commercial.plans()), 6)


if __name__ == "__main__":
    unittest.main()
