"""Servidor local que reproduz a API de Cobrança v3 do Banco Inter para os testes (TLS mútuo real).

Não substitui a homologação no sandbox do Inter: serve para verificar o adaptador (autenticação,
certificado do cliente, criação, consulta e situações) e a conciliação sem acesso à internet.
"""

from __future__ import annotations

import json
import ssl
import threading
import urllib.parse
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def _cert(folder: Path, name: str):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    import ipaddress
    k = ec.generate_private_key(ec.SECP256R1())
    subj = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.now(timezone.utc)
    c = (x509.CertificateBuilder().subject_name(subj).issuer_name(subj).public_key(k.public_key())
         .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
         .not_valid_after(now + timedelta(days=30))
         .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                                                     x509.DNSName("localhost")]), False)
         .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
         .sign(k, hashes.SHA256()))
    cf, kf = folder / f"{name}.crt", folder / f"{name}.key"
    cf.write_bytes(c.public_bytes(serialization.Encoding.PEM))
    kf.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                   serialization.NoEncryption()))
    return cf, kf


class FakeInter:
    def __init__(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self.server_cert, self.server_key = _cert(folder, "inter-servidor")
        self.client_cert, self.client_key = _cert(folder, "aplicacao-cliente")
        self.charges: dict[str, dict] = {}
        self.calls: list[tuple[str, str]] = []
        self.client_id, self.client_secret = "cid-teste", "segredo-teste"
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # noqa: D401
                pass

            def _send(self, code, obj):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def _auth(self):
                return self.headers.get("Authorization") == "Bearer tok-123"

            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                fake.calls.append(("POST", self.path))
                if self.path == "/oauth/v2/token":
                    f = dict(urllib.parse.parse_qsl(body.decode()))
                    if f.get("client_id") == fake.client_id and f.get("client_secret") == fake.client_secret \
                            and "boleto-cobranca.write" in f.get("scope", ""):
                        return self._send(200, {"access_token": "tok-123", "expires_in": 3600})
                    return self._send(401, {"title": "invalid client"})
                if not self._auth():
                    return self._send(401, {})
                if self.path == "/cobranca/v3/cobrancas":
                    d = json.loads(body)
                    code = f"cod-{len(fake.charges) + 1:04d}"
                    fake.charges[code] = {"codigoSolicitacao": code, "seuNumero": d["seuNumero"],
                                          "situacao": "A_RECEBER", "valorNominal": d["valorNominal"],
                                          "pagador": d["pagador"]}
                    return self._send(200, {"codigoSolicitacao": code})
                return self._send(404, {})

            def do_GET(self):  # noqa: N802
                fake.calls.append(("GET", self.path))
                if not self._auth():
                    return self._send(401, {})
                code = self.path.rsplit("/", 1)[-1]
                if self.path.startswith("/cobranca/v3/cobrancas/") and code in fake.charges:
                    return self._send(200, {"cobranca": fake.charges[code], "boleto": {}, "pix": {}})
                return self._send(404, {})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self.server_cert, self.server_key)
        ctx.verify_mode = ssl.CERT_REQUIRED                       # TLS mútuo, como o Inter
        ctx.load_verify_locations(self.client_cert)
        self.httpd.socket = ctx.wrap_socket(self.httpd.socket, server_side=True)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        return f"https://127.0.0.1:{self.port}"

    def pay(self, code: str, value: float, status: str = "RECEBIDO") -> dict:
        ch = self.charges[code]
        ch.update(situacao=status, valorTotalRecebido=value, dataSituacao=datetime.now(timezone.utc).isoformat())
        return ch

    def webhook_body(self, code: str, status: str) -> bytes:
        return json.dumps([{"codigoSolicitacao": code, "situacao": status, "dataHoraSituacao": "2026-10-21T12:00:00Z",
                            "valorTotalRecebido": 499.0}]).encode()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
