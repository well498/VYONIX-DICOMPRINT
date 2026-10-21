"""Assistente local: só 127.0.0.1, token de uso único trocado por cookie, POST exige cabeçalho próprio."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path


class WizardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vyx-wiz-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        os.environ["VYONIX_DEPLOY_ROOT"] = str(self.tmp)
        self.addCleanup(os.environ.pop, "VYONIX_DEPLOY_ROOT", None)

    def test_token_cookie_and_csrf_header(self):
        import socket
        from vyonix_deploy import wizard
        from vyonix_deploy.service import Deploy
        d = Deploy()
        self.addCleanup(d.close)
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        captured = {}
        orig_print = __builtins__["print"] if isinstance(__builtins__, dict) else __builtins__.print

        import builtins

        def fake_print(*a, **k):
            captured.setdefault("lines", []).append(" ".join(map(str, a)))
        builtins.print = fake_print
        try:
            th = threading.Thread(target=wizard.serve, args=(d,), kwargs={"port": port, "open_browser": False},
                                  daemon=True)
            th.start()
            for _ in range(100):
                if captured.get("lines"):
                    break
                time.sleep(0.05)
        finally:
            builtins.print = orig_print
        url = captured["lines"][0].split(": ", 1)[1]
        self.assertTrue(url.startswith(f"http://127.0.0.1:{port}/?t="))
        base = f"http://127.0.0.1:{port}"

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        op = urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))
        with self.assertRaises(urllib.error.HTTPError) as cm:        # sem cookie
            op.open(base + "/api/state")
        self.assertEqual(cm.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            op.open(url)
        self.assertEqual(cm.exception.code, 303)
        cookie = cm.exception.headers["Set-Cookie"].split(";")[0]
        self.assertIn("HttpOnly", cm.exception.headers["Set-Cookie"])
        with self.assertRaises(urllib.error.HTTPError) as cm:        # token não vale duas vezes
            op.open(url)
        self.assertEqual(cm.exception.code, 403)
        st = json.loads(op.open(urllib.request.Request(base + "/api/state", headers={"Cookie": cookie})).read())
        self.assertFalse(st["installed"])
        req = urllib.request.Request(base + "/api/plan", data=b'{"kind":"install"}', method="POST",
                                     headers={"Cookie": cookie, "Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as cm:        # sem o cabeçalho do assistente
            op.open(req)
        self.assertEqual(cm.exception.code, 403)
        req.add_header("X-Vyonix-Wizard", "1")
        try:
            r = op.open(req)
            plan = json.loads(r.read())
            self.assertIn("items", plan)                             # Windows: plano gerado
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read())
            self.assertEqual(exc.code, 409)                          # outros sistemas: impeditivo, nada alterado
            self.assertTrue(any(b["id"] == "os" for b in body["blockers"]))


if __name__ == "__main__":
    unittest.main()
