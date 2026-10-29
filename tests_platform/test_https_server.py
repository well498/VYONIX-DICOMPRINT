"""Servidor HTTPS do Core com redirecionamento de http:// na mesma porta (relato da homologação de 28/10/2026):
HTTPS normal (vários pedidos na mesma conexão, envio grande, esquema https visto pelo aplicativo), http:// recebe 301
para https:// com o mesmo host e caminho, Host malicioso não injeta cabeçalho, lixo não derruba o servidor e o modo
sem redirecionamento continua disponível."""


import http.client
import os
import shutil
import socket
import ssl
import tempfile
import threading
import time
import unittest
from pathlib import Path


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class HttpsServer(unittest.TestCase):
    redirect = True

    def setUp(self):
        from fastapi import FastAPI, Request
        from vyonix.api.https_server import make_server
        from vyonix.cli import ensure_tls
        from vyonix.config import Config
        tmp = Path(tempfile.mkdtemp(prefix="vyx-https-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        cert, key = ensure_tls(Config(data_dir=tmp))
        app = FastAPI()

        @app.get("/x")
        def x(request: Request):
            return {"scheme": request.url.scheme}

        @app.post("/up")
        async def up(request: Request):
            return {"n": len(await request.body())}
        self.port = free_port()
        self.srv = make_server(app, host="127.0.0.1", port=self.port, certfile=cert, keyfile=key,
                               redirect=self.redirect, log_level="warning")
        th = threading.Thread(target=self.srv.run, daemon=True)
        th.start()
        for _ in range(100):
            if self.srv.started:
                break
            time.sleep(0.05)
        self.addCleanup(lambda: (setattr(self.srv, "should_exit", True), th.join(10)))

    def https(self):
        return http.client.HTTPSConnection("127.0.0.1", self.port, context=ssl._create_unverified_context(),
                                           timeout=15)

    def test_https_keepalive_and_large_upload(self):
        c = self.https()
        for _ in range(3):
            c.request("GET", "/x")
            r = c.getresponse()
            self.assertEqual((r.status, r.read()), (200, b'{"scheme":"https"}'))
        c.request("POST", "/up", body=os.urandom(6_000_000))
        self.assertEqual(c.getresponse().read(), b'{"n":6000000}')

    def test_http_redirects_to_https_same_host_and_path(self):
        h = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h.request("GET", "/pacientes?x=1", headers={"Host": f"192.168.0.20:{self.port}"})
        r = h.getresponse()
        self.assertEqual((r.status, r.getheader("Location")), (301, f"https://192.168.0.20:{self.port}/pacientes?x=1"))
        self.assertIn("conexão segura", r.read().decode("utf-8"))

    def test_hostile_host_and_garbage(self):
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as s:
            s.sendall(b"GET /a HTTP/1.1\r\nHost: evil.com\r\n X-Injected: 1\r\n\r\n")
            data = s.recv(4096)
        self.assertIn(b"Location: https://evil.com:", data)
        self.assertNotIn(b"X-Injected", data.split(b"\r\n\r\n")[0])
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as s:
            s.sendall(b"GET http://x/\r\nHost: a\r\nb\r\n\r\n" + b"\x00" * 20)
            self.assertTrue(s.recv(4096).startswith(b"HTTP/1.1 301"))
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as s:
            s.sendall(b"\x16\x03\x01\x00\x05garbage")                  # handshake TLS inválido
            s.recv(1024)
        self.test_https_keepalive_and_large_upload()                    # servidor segue atendendo


class PlainHttps(HttpsServer):
    redirect = False
    test_http_redirects_to_https_same_host_and_path = test_hostile_host_and_garbage = None


if __name__ == "__main__":
    unittest.main()
