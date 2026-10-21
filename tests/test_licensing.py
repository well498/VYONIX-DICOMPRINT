"""Fase 8 — licenciamento offline com Ed25519 e ferramenta de emissão separada."""

import json
import unittest
from datetime import datetime, timedelta, timezone

from app.licensing import ed25519
from tests.helpers import TempDirTestCase

try:
    import cryptography  # noqa: F401
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False


class Ed25519Test(unittest.TestCase):
    """Vetores oficiais da RFC 8032 (seção 7.1)."""

    VECTORS = [
        ("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
         "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
        ("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
         "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
        ("fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025", "af82",
         "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"),
    ]

    def test_rfc8032_vectors(self):
        for pk, msg, sig in self.VECTORS:
            pk, msg, sig = bytes.fromhex(pk), bytes.fromhex(msg), bytes.fromhex(sig)
            self.assertTrue(ed25519.verify(pk, msg, sig))
            self.assertFalse(ed25519.verify(pk, msg + b"\x00", sig))
            bad = bytearray(sig)
            bad[10] ^= 1
            self.assertFalse(ed25519.verify(pk, msg, bytes(bad)))
        self.assertFalse(ed25519.verify(b"\x00" * 31, b"", b"\x00" * 64))


@unittest.skipUnless(HAS_CRYPTO, "cryptography não instalada (necessária só para emitir licenças nos testes)")
class LicenseFlowTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        import license_admin.__main__ as admin
        from app.bootstrap import bootstrap
        from app.licensing import keys
        self.admin = admin
        self.keydir = self.tmp / "cofre"
        out = []
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            admin.main(["keygen", "--key-id", "teste-1", "--out", str(self.keydir)])
        line = [ln for ln in buf.getvalue().splitlines() if '"teste-1"' in ln][0]
        keys.PUBLIC_KEYS["teste-1"] = line.split('"')[3]
        self.addCleanup(keys.PUBLIC_KEYS.pop, "teste-1", None)
        self.key = self.keydir / "vyonix-teste-1.private.pem"
        self.ctx = bootstrap(data_dir=self.tmp / "data")
        _ = out

    def tearDown(self):
        self.ctx.close()
        super().tearDown()

    def issue(self, *extra, request=None, name="lic.vylic"):
        import contextlib
        import io
        path = self.tmp / name
        with contextlib.redirect_stdout(io.StringIO()):
            code = self.admin.main(["issue", "--key", str(self.key), "--key-id", "teste-1", "--request",
                                    request or self.ctx.license.request_code(), "--licensee", "Clínica Teste",
                                    "--out", str(path), *extra])
        self.assertEqual(code, 0)
        return path.read_text(encoding="utf-8")

    def test_request_code_has_no_patient_data_and_roundtrips(self):
        from app.licensing.license import parse_request
        self.ctx.settings.update({"site.name": "Unidade Centro"}, actor="t")
        req = parse_request(self.ctx.license.request_code())
        self.assertEqual(req["installation_id"], self.ctx.settings.get("system.installation_id"))
        self.assertEqual(len(req["machine_id"]), 32)
        self.assertEqual(req["site"], "Unidade Centro")
        self.assertEqual(set(req), {"v", "product", "installation_id", "machine_id", "app_version", "site",
                                    "requested_at"})

    def test_install_valid_and_history(self):
        st0 = self.ctx.license.status()
        self.assertEqual(st0.state.value, "not_activated")
        st = self.ctx.license.install(self.issue("--edition", "profissional", "--days", "365"), actor="t")
        self.assertEqual(st.state.value, "valid", st.message)
        self.assertEqual(st.edition, "Profissional")
        self.assertIn("print_scp", st.features)
        lic = self.ctx.license.license_data()
        self.assertEqual((lic.licensee, lic.max_devices), ("Clínica Teste", 10))
        # Nova licença substitui a anterior
        self.ctx.license.install(self.issue("--edition", "corporativo", "--days", "0", name="b.vylic"), actor="t")
        self.assertEqual(self.ctx.license.status().edition, "Corporativo")
        self.assertIsNone(self.ctx.license.status().expires_at)
        self.assertEqual([h["status"] for h in self.ctx.license.history()], ["active", "superseded"])
        self.assertTrue((self.keydir / "emitidas.csv").exists())
        self.assertIn("license.install", [e.action for e in self.ctx.events.query()])

    def test_rejections(self):
        from app.core.errors import ValidationError
        from app.licensing.license import b64d, b64e
        text = self.issue()
        # Alteração do conteúdo sem nova assinatura
        doc = json.loads(text)
        payload = json.loads(b64d(doc["payload"]))
        payload["max_devices"] = 999
        doc["payload"] = b64e(json.dumps(payload).encode())
        with self.assertRaisesRegex(ValidationError, "assinatura"):
            self.ctx.license.install(json.dumps(doc), actor="t")
        # Chave desconhecida
        doc = json.loads(text)
        doc["key_id"] = "outra"
        with self.assertRaisesRegex(ValidationError, "desconhecida"):
            self.ctx.license.install(json.dumps(doc), actor="t")
        # Outra instalação
        from app.licensing.license import REQUEST_PREFIX, canonical, parse_request
        req = parse_request(self.ctx.license.request_code())
        req["installation_id"] = "outra-instalacao"
        other = REQUEST_PREFIX + b64e(canonical(req))
        with self.assertRaisesRegex(ValidationError, "outra instalação"):
            self.ctx.license.install(self.issue(request=other, name="o.vylic"), actor="t")
        # Arquivo qualquer
        with self.assertRaises(ValidationError):
            self.ctx.license.install("não é licença", actor="t")
        self.assertEqual(self.ctx.license.status().state.value, "not_activated")
        self.assertIn("license.rejected", [e.action for e in self.ctx.events.query()])

    def test_other_computer_expiry_clock_and_tampered_db(self):
        from app.licensing.license import LicenseService
        self.ctx.license.install(self.issue("--days", "30"), actor="t")
        self.assertEqual(self.ctx.license.status().state.value, "valid")
        other_pc = LicenseService(self.ctx.db, self.ctx.events, self.ctx.settings.get, machine_id=lambda: "x" * 32)
        self.assertEqual(other_pc.status().state.value, "hardware_mismatch")
        future = LicenseService(self.ctx.db, self.ctx.events, self.ctx.settings.get,
                                clock=lambda: datetime.now(timezone.utc) + timedelta(days=40))
        self.assertEqual(future.status().state.value, "expired")
        # Relógio atrasado depois de já ter sido visto mais adiante
        past = LicenseService(self.ctx.db, self.ctx.events, self.ctx.settings.get,
                              clock=lambda: datetime.now(timezone.utc) - timedelta(days=10))
        st = past.status()
        self.assertEqual(st.state.value, "invalid")
        self.assertIn("relógio", st.message)
        # Registro adulterado diretamente no banco é detectado na verificação
        self.ctx.db.connection().execute("UPDATE licenses SET raw = replace(raw, 'a', 'b') WHERE status='active'")
        self.assertNotEqual(self.ctx.license.status(refresh=True).state.value, "valid")

    def test_enforced_policy(self):
        self.ctx.license.enforced = True
        self.assertTrue(self.ctx.license.evaluation_mode())       # sem licença: avaliação, tudo funciona
        self.assertTrue(self.ctx.license.allows("print_scp"))
        self.ctx.license.install(self.issue("--edition", "essencial"), actor="t")
        self.assertFalse(self.ctx.license.evaluation_mode())
        self.assertFalse(self.ctx.license.allows("print_scp"))
        self.assertFalse(self.ctx.license.allows("rules"))
        # Print SCP não inicia
        self.ctx.print_scp.start()
        st = self.ctx.print_scp.status()
        self.assertEqual(st.state.value, "stopped")
        self.assertIn("licença", st.detail)
        # Regras ignoradas, com explicação
        ev = self.ctx.rules.evaluate({"modality": "CT"})
        self.assertIn("licença", ev.explanation[0])
        # Limite de 2 equipamentos autorizados
        from app.core.errors import ValidationError
        for i in range(2):
            self.ctx.devices.create({"name": f"D{i}", "ae_title": f"AE{i}"}, actor="t", authorized=True)
        with self.assertRaisesRegex(ValidationError, "2 equipamento"):
            self.ctx.devices.create({"name": "D3", "ae_title": "AE3"}, actor="t", authorized=True)
        d = self.ctx.devices.create({"name": "D4", "ae_title": "AE4"}, actor="t", authorized=False)
        with self.assertRaises(ValidationError):
            self.ctx.devices.set_authorized(d.id, True, actor="t")

    def test_admin_verify_command(self):
        import contextlib
        import io
        self.issue()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = self.admin.main(["verify", str(self.tmp / "lic.vylic")])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(buf.getvalue())["assinatura_valida"])


class PackagingGuardTest(unittest.TestCase):
    def test_no_private_key_in_repository_or_app(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        offenders = [p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts
                     and (p.suffix.lower() in (".pem", ".key") or b"PRIVATE KEY" in p.read_bytes()[:4096]
                          and p.suffix not in (".py", ".md"))]
        self.assertEqual(offenders, [])
        spec = (root / "Vyonix.spec").read_text(encoding="utf-8")
        self.assertIn('"license_admin"', spec)
        import app.licensing.license as lic
        self.assertFalse(hasattr(lic, "sign"))
