"""Ferramenta do passo 4 do incidente (``tools/apply_key_rotation.py``) com arquivos exportados pelo License
Manager REAL: a chave nova entra em PUBLIC_KEYS/KEY_SCOPES, a antiga fica restrita aos documentos legítimos,
o resultado é reimportado; entradas perigosas ou inconsistentes são recusadas sem alterar nada."""

import json
import re
import shutil
import sys
from pathlib import Path

from tests.test_licensing import Base

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import apply_key_rotation as rot  # noqa: E402


class KeyRotationToolTest(Base):
    def setUp(self):
        super().setUp()
        self._orig = rot.KEY_ID
        rot.KEY_ID = re.compile(r"^[a-z0-9-]+$")            # chaves de teste ("teste-01") fora do padrão vyx-AAAA-NN
        self.addCleanup(setattr, rot, "KEY_ID", self._orig)
        self.lic, _ = self.activate()
        self.old_id = next(iter(self.keys))
        new = self.lm.generate_key(self.admin, "teste-02", "outra-frase-senha-456")
        self.new_hex = new["public_hex"]
        self.pub = self.tmp / "pub.txt"
        self.pub.write_text(self.lm.export_public_line("teste-02"), encoding="utf-8")
        self.restr = self.lm.export_key_restriction(self.admin, self.old_id, self.tmp / "exp")["json"]
        self.keys_file = self.tmp / "keys.py"
        src = (ROOT / "app" / "licensing" / "keys.py").read_text(encoding="utf-8")
        old_hex = self.keys[self.old_id]
        src = src.replace('PUBLIC_KEYS: dict[str, str] = {', 'PUBLIC_KEYS: dict[str, str] = {\n'
                          f'    "{self.old_id}": "{old_hex}",', 1)
        src = src.replace('KEY_SCOPES: dict[str, tuple[str, ...]] = {', 'KEY_SCOPES: dict[str, tuple[str, ...]] = {\n'
                          f'    "{self.old_id}": ("license", "authorization", "revalidation", "revocation"),', 1)
        self.keys_file.write_text(src, encoding="utf-8")

    def run_tool(self, *extra, pub=None, restr=None):
        return rot.main(["--public", str(pub or self.pub), "--restriction", str(restr or self.restr),
                         "--keys-file", str(self.keys_file), *extra])

    def test_apply_and_resulting_policy(self):
        before = self.keys_file.read_text(encoding="utf-8")
        self.assertEqual(self.run_tool("--dry-run"), 0)
        self.assertEqual(self.keys_file.read_text(encoding="utf-8"), before)
        self.assertEqual(self.run_tool(), 0)
        mod = rot._load(self.keys_file)
        self.assertEqual(mod.PUBLIC_KEYS["teste-02"], self.new_hex)
        self.assertEqual(set(mod.KEY_SCOPES["teste-02"]), {"license", "authorization", "revalidation", "revocation"})
        from vyonix_protocol import formats as F
        legit = F.parse_signed(self.lic["document"], F.LICENSE_FORMAT)
        self.assertIsNone(mod.key_policy_error(self.old_id, legit.signed))           # legítima continua aceita
        payload = dict(legit.payload)
        payload["expires_at"] = "2099-12-31T23:59:59Z"
        _k, forged = self.lm._sign_doc(F.LICENSE_FORMAT, payload)
        self.assertIsNotNone(mod.key_policy_error(self.old_id, F.parse_signed(forged, F.LICENSE_FORMAT).signed))
        self.assertIsNone(mod.key_policy_error("teste-02", b"qualquer"))              # chave nova sem restrição
        self.assertEqual(self.run_tool(), 2)                                         # segunda aplicação recusada

    def test_refusals_leave_file_untouched(self):
        before = self.keys_file.read_text(encoding="utf-8")
        bad = self.tmp / "bad"
        bad.mkdir()
        priv = bad / "pub.txt"
        priv.write_text(self.pub.read_text(encoding="utf-8") + "\n-----BEGIN PRIVATE KEY-----\nMC4CAQ\n", encoding="utf-8")
        self.assertEqual(self.run_tool(pub=priv), 2)
        badhex = bad / "hex.txt"
        badhex.write_text('"teste-03": "' + "ab" * 31 + '",', encoding="utf-8")
        self.assertEqual(self.run_tool(pub=badhex), 2)
        m = json.loads(self.restr.read_text(encoding="utf-8"))
        for change in ({"documents": [], "count": 0}, {"key_id": "desconhecida-01"}, {"format": "outro/1"},
                       {"documents": [{"kind": "license", "ref": "x", "sha256": "zz"}], "count": 1},
                       {"count": m["count"] + 1}):
            f = bad / "r.json"
            f.write_text(json.dumps({**m, **change}), encoding="utf-8")
            self.assertEqual(self.run_tool(restr=f), 2, change)
        same = bad / "same.txt"
        same.write_text(self.lm.export_public_line(self.old_id), encoding="utf-8")
        self.assertEqual(self.run_tool(pub=same), 2)                                 # chave já confiada
        self.assertEqual(self.keys_file.read_text(encoding="utf-8"), before)
