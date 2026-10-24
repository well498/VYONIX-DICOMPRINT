"""Incidente de chave (INC-2026-10-23): restrição de uma chave comprometida sem invalidar os clientes.

Fluxo verificado de ponta a ponta com o License Manager real e o VYONIX DICOM Print real (licenciamento):
1. licença legítima emitida e instalada;
2. o License Manager exporta a lista de documentos legítimos da chave;
3. com a chave sob restrição, a licença legítima continua aceita;
4. um documento novo assinado com a MESMA chave (como faria quem tem a chave vazada) é recusado;
5. a chave nova (rotação) é aceita normalmente.
"""

import json

from app.core.contracts import LicenseState
from app.licensing.keys import key_policy_error, signed_digest
from tests.test_licensing import Base


class KeyRestrictionTest(Base):
    def test_restricted_key_keeps_legit_and_refuses_new(self):
        lic, st = self.activate()
        self.assertEqual(st.state, LicenseState.VALID, st.message)
        key_id = lic["key_id"] if "key_id" in lic else next(iter(self.keys))

        out = self.lm.export_key_restriction(self.admin, key_id, self.tmp / "exp")
        manifest = json.loads(out["json"].read_text(encoding="utf-8"))
        self.assertEqual(manifest["format"], "vyonix-keyrestriction/1")
        self.assertEqual(manifest["key_id"], key_id)
        self.assertGreaterEqual(manifest["count"], 1)
        self.assertIn(lic["license_id"], {d["ref"] for d in manifest["documents"] if d["kind"] == "license"})
        snippet = out["snippet"].read_text(encoding="utf-8")
        self.assertIn(f'"{key_id}": frozenset({{', snippet)
        for h in out["hashes"]:
            self.assertIn(h, snippet)
        text = out["json"].read_text(encoding="utf-8") + snippet
        self.assertNotIn("PRIVATE KEY", text)
        self.assertNotIn("Clínica Teste Ltda", text)          # sem dados do cliente

        restricted = {key_id: frozenset(out["hashes"])}
        self.client.svc.restricted_keys = restricted
        self.assertEqual(self.client.svc.check(lic["document"]).status.state, LicenseState.VALID)

        # documento novo com a mesma chave (o que um atacante com a chave faria): assinatura válida, recusado
        from vyonix_protocol import formats as F
        payload = dict(F.parse_signed(lic["document"], F.LICENSE_FORMAT).payload)
        payload["expires_at"] = "2099-12-31T23:59:59Z"            # licença forjada "perpétua"
        _k, forged = self.lm._sign_doc(F.LICENSE_FORMAT, payload)
        v = self.client.svc.check(forged)
        self.assertEqual(v.status.state, LicenseState.INVALID)
        self.assertIn("retirada por segurança", v.status.message)

        # rotação: chave nova gerada no License Manager e confiada pelo produto
        new = self.lm.generate_key(self.admin, "teste-02", "outra-frase-senha-456")
        self.lm.set_key_status(self.admin, "teste-02", "active")
        self.lm.unlock_key(self.admin, "outra-frase-senha-456")
        self.client.svc.public_keys = {**self.keys, "teste-02": new["public_hex"]}
        rotated = self.lm.renew(self.admin, lic["license_id"], ltype="annual")
        self.assertEqual(json.loads(rotated["document"])["key_id"], "teste-02")
        self.assertEqual(self.client.svc.check(rotated["document"]).status.state, LicenseState.VALID)

    def test_policy_function(self):
        self.assertIsNone(key_policy_error("k", b"abc", {}))
        allowed = {"k": frozenset({signed_digest(b"abc")})}
        self.assertIsNone(key_policy_error("k", b"abc", allowed))
        self.assertIn("retirada por segurança", key_policy_error("k", b"abd", allowed))
        self.assertIsNone(key_policy_error("outra", b"abd", allowed))

    def test_export_requires_keys_permission(self):
        from license_manager.security import PermissionDenied
        self.lm.create_user(self.admin, "emissor", "Emissor", "issuer", "Senha-Emissor-789")
        emissor = self.lm.login("emissor", "Senha-Emissor-789")
        with self.assertRaises(PermissionDenied):
            self.lm.export_key_restriction(emissor, next(iter(self.keys)), self.tmp / "exp2")

    def test_production_has_no_restriction_yet(self):
        """Até a atualização com a lista exportada pelo fornecedor, nenhuma chave está restrita."""
        from app.licensing.keys import RESTRICTED_KEYS
        self.assertEqual(RESTRICTED_KEYS, {})


class LicenseServerRestrictionTest(Base):
    def test_server_refuses_forged_license_of_restricted_key(self):
        from license_server.core import ServerCore, ServerError, SessionUser
        from vyonix_protocol import crypto
        from vyonix_protocol import formats as F
        lic, _st = self.activate()
        key_id = json.loads(lic["document"])["key_id"]
        hashes = self.lm.export_key_restriction(self.admin, key_id, self.tmp / "exp")["hashes"]
        core = ServerCore(self.tmp / "srv", signer=("srv-teste", crypto.generate_ed25519()), license_keys=self.keys,
                          restricted_keys={key_id: frozenset(hashes)}, clock=lambda: self.pc.clock.wall)
        self.addCleanup(core.close)
        core.create_user(None, "comercial", "Comercial", "admin", "Comercial-Senha-1")
        uid = core.db.conn().execute("SELECT id FROM users WHERE username = 'comercial'").fetchone()["id"]
        by = SessionUser(uid, "comercial", "Comercial", "admin")
        payload = dict(F.parse_signed(lic["document"], F.LICENSE_FORMAT).payload)
        payload["license_id"] = "VYX-2026-FORJADA1"
        _k, forged = self.lm._sign_doc(F.LICENSE_FORMAT, payload)
        with self.assertRaises(ServerError) as cm:
            core.register_license(by, forged, price_cents=100)
        self.assertIn("retirada por segurança", str(cm.exception))
        core.register_license(by, lic["document"], price_cents=49900)       # a legítima continua aceita
