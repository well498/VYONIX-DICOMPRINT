"""Entrega do Viewer pelo CORE: rotas, política de conteúdo com hash dos scripts embutidos, caminho
fora da pasta recusado e resposta clara quando o pacote do OHIF não está instalado.

Usa uma pasta com um ``index.html`` mínimo — testa o código de entrega do CORE, não o OHIF (o OHIF
real é compilado e aberto no navegador pelo CI ``viewer.yml``).
"""

from __future__ import annotations

import base64
import hashlib
import tempfile
import unittest
from pathlib import Path


class ViewerServing(unittest.TestCase):
    def app(self, dist):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from vyonix.api import viewer
        a = FastAPI()
        viewer.mount(a, dist)
        return TestClient(a)

    def test_missing_package_is_explicit_404(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.app(Path(d)).get("/viewer/")
            self.assertEqual(r.status_code, 404)
            self.assertIn("não instalado", r.json()["message"])

    def test_serves_index_assets_and_csp_hashes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "dist"
            (root / "sub").mkdir(parents=True)
            inline = "\n      window.PUBLIC_URL = '/viewer/';\n    "
            (root / "index.html").write_text(f"<html><head><script>{inline}</script>"
                                             "<script src='/viewer/app.js'></script></head></html>", encoding="utf-8")
            (root / "app.js").write_text("console.log(1)", encoding="utf-8")
            (root / "sub" / "codec.wasm").write_bytes(b"\0asm")
            (Path(d) / "segredo.txt").write_text("fora", encoding="utf-8")
            c = self.app(root)
            r = c.get("/viewer/study/123")                     # rota do OHIF → index.html
            self.assertEqual(r.status_code, 200)
            csp = r.headers["content-security-policy"]
            h = base64.b64encode(hashlib.sha256(inline.encode()).digest()).decode()
            self.assertIn(f"'sha256-{h}'", csp)
            self.assertNotIn("script-src 'self' 'unsafe-inline'", csp)
            self.assertIn("'wasm-unsafe-eval'", csp)
            self.assertIn("frame-ancestors 'none'", csp)
            self.assertEqual(c.get("/viewer/app.js").text, "console.log(1)")
            self.assertEqual(c.get("/viewer/sub/codec.wasm").headers["content-type"], "application/wasm")
            self.assertNotEqual(c.get("/viewer/../segredo.txt").text, "fora")
            self.assertNotEqual(c.get("/viewer/%2e%2e/segredo.txt").text, "fora")


if __name__ == "__main__":
    unittest.main()
