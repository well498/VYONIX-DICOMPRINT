"""``verificar``/``abrir`` sem --porta usam a porta gravada na instalação (CI 2.13: reversão após 2.7 mover a porta)."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from vyonix_deploy import cli


class InstalledPort(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("VYONIX_DEPLOY_ROOT")
        os.environ["VYONIX_DEPLOY_ROOT"] = self.tmp.name
        self.cfg = Path(self.tmp.name) / "data" / "Platform" / "config.json"
        self.cfg.parent.mkdir(parents=True)

    def tearDown(self):
        if self.old is None:
            os.environ.pop("VYONIX_DEPLOY_ROOT", None)
        else:
            os.environ["VYONIX_DEPLOY_ROOT"] = self.old
        self.tmp.cleanup()

    def test_reads_moved_port(self):
        self.cfg.write_text(json.dumps({"port": 8445}), encoding="utf-8")
        self.assertEqual(cli.installed_https_port(), 8445)

    def test_bom_tolerated(self):
        self.cfg.write_bytes(b"\xef\xbb\xbf" + json.dumps({"port": 8460}).encode())
        self.assertEqual(cli.installed_https_port(), 8460)

    def test_default_when_missing_or_invalid(self):
        self.assertEqual(cli.installed_https_port(), 8444)
        self.cfg.write_text("{not json", encoding="utf-8")
        self.assertEqual(cli.installed_https_port(), 8444)
        self.cfg.write_text(json.dumps({"port": 0}), encoding="utf-8")
        self.assertEqual(cli.installed_https_port(), 8444)

    def test_reversal_and_recovery_call_verificar_without_fixed_port(self):
        rec = Path(__file__).resolve().parents[1] / "installer" / "recuperacao"
        for f in ("Reverter_VYONIX.ps1", "Recuperar_VYONIX.ps1"):
            txt = (rec / f).read_text(encoding="utf-8-sig")
            for line in txt.splitlines():
                if " verificar " in line:
                    self.assertNotIn("--porta 8444", line, f)


if __name__ == "__main__":
    unittest.main()
