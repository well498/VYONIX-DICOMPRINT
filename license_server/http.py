"""Camada HTTPS do VYONIX License Server (biblioteca padrão + TLS 1.2+)."""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import ssl
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from license_server import APP_NAME, __version__
from license_server.core import ServerCore, ServerError, json_body

log = logging.getLogger("license_server")
MAX_BODY = 512 * 1024
DEFAULT_ADMIN_NETWORKS = ("127.0.0.0/8", "::1/128", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")


def ensure_certificate(folder: Path, hostnames: list[str]) -> tuple[Path, Path]:
    """Certificado autoassinado (ECDSA P-256), se a pasta não tiver o certificado da instituição."""
    folder.mkdir(parents=True, exist_ok=True)
    cert, key = folder / "cert.pem", folder / "key.pem"
    if cert.exists() and key.exists():
        return cert, key
    from datetime import datetime, timedelta, timezone

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    k = ec.generate_private_key(ec.SECP256R1())
    names = [h for h in hostnames if h] or ["localhost"]
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0]),
                         x509.NameAttribute(NameOID.ORGANIZATION_NAME, "VYONIX License Server")])
    alt = []
    for h in dict.fromkeys(names + ["localhost", "127.0.0.1"]):
        try:
            alt.append(x509.IPAddress(ipaddress.ip_address(h)))
        except ValueError:
            alt.append(x509.DNSName(h))
    now = datetime.now(timezone.utc)
    c = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(k.public_key())
         .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
         .not_valid_after(now + timedelta(days=3650)).add_extension(x509.SubjectAlternativeName(alt), False)
         .sign(k, hashes.SHA256()))
    key.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()))
    try:
        key.chmod(0o600)
    except OSError:
        pass
    cert.write_bytes(c.public_bytes(serialization.Encoding.PEM))
    return cert, key


def certificate_pin(cert_file: Path) -> str:
    """SHA-256 do certificado (DER) — gravado nas licenças online para conferência pelo VYONIX."""
    import hashlib
    der = ssl.PEM_cert_to_DER_cert(Path(cert_file).read_text())
    return hashlib.sha256(der).hexdigest()


class LicenseHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, core: ServerCore, *, cert: Path, key: Path, admin_networks=DEFAULT_ADMIN_NETWORKS):
        super().__init__(addr, Handler)
        self.core = core
        self.admin_networks = [ipaddress.ip_network(n) for n in admin_networks]
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(str(cert), str(key))
        self.socket = ctx.wrap_socket(self.socket, server_side=True, do_handshake_on_connect=False)

    def finish_request(self, request, client_address) -> None:
        """Negociação TLS na thread da conexão (um cliente lento não bloqueia os demais)."""
        try:
            request.settimeout(15)
            request.do_handshake()
        except (ssl.SSLError, OSError):
            return
        super().finish_request(request, client_address)

    def admin_allowed(self, ip: str) -> bool:
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(a in n for n in self.admin_networks)


class Handler(BaseHTTPRequestHandler):
    server: LicenseHTTPServer
    server_version = f"VYONIX-License-Server/{__version__}"
    sys_version = ""

    def log_message(self, fmt, *args) -> None:  # noqa: D401 - sem dados sensíveis no log
        log.info("%s %s", self.client_address[0], fmt % args)

    def handle_one_request(self) -> None:
        try:
            super().handle_one_request()
        except (ssl.SSLError, ConnectionError, TimeoutError):
            self.close_connection = True

    # ------------------------------------------------------------------ utilidades
    def _send(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Strict-Transport-Security", "max-age=31536000")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ServerError(413, "Requisição muito grande.")
        return self.rfile.read(n) if n else b""

    def _user(self):
        auth = self.headers.get("Authorization") or ""
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        return self.server.core.session(token), token

    def _admin_gate(self) -> None:
        if not self.server.admin_allowed(self.client_address[0]):
            raise ServerError(403, "Administração não permitida a partir deste endereço (admin_networks).")

    # ------------------------------------------------------------------ rotas
    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch("PUT")

    def _dispatch(self, method: str) -> None:
        ip = self.client_address[0]
        u = urllib.parse.urlsplit(self.path)
        path, q = u.path, dict(urllib.parse.parse_qsl(u.query))
        core = self.server.core
        try:
            if path == "/v1/health" and method == "GET":
                return self._send(200, {"ok": True, "app": APP_NAME, "version": __version__,
                                        "signing_key": core.signer[0] if core.signer else None})
            if path == "/v1/authorize" and method == "POST":
                return self._send(200, core.authorize(json_body(self._body()), ip))
            m = re.fullmatch(r"/v1/billing/(\w+)/([A-Za-z0-9_-]{16,128})", path)
            if m and method == "POST":
                return self._send(200, core.webhook(m[1], m[2], self._body(), ip))
            if path.startswith("/v1/admin/"):
                self._admin_gate()
                return self._admin(method, path[len("/v1/admin"):], q, ip)
            raise ServerError(404, "Não encontrado.")
        except ServerError as exc:
            self._send(exc.status, {"error": str(exc)})
        except Exception:  # noqa: BLE001
            log.exception("Erro interno")
            self._send(500, {"error": "Erro interno do servidor."})
        finally:
            try:
                core.db.close()
            except Exception:  # noqa: BLE001
                pass

    def _admin(self, method: str, path: str, q: dict, ip: str) -> None:
        core = self.server.core
        if path == "/login" and method == "POST":
            d = json_body(self._body())
            token, user = core.login(str(d.get("username") or ""), str(d.get("password") or ""), ip)
            return self._send(200, {"token": token, "user": user.__dict__, "minutes": core.session_minutes})
        user, token = self._user()
        if path == "/logout" and method == "POST":
            core.logout(token)
            return self._send(200, {"ok": True})
        if path == "/me":
            return self._send(200, {"user": user.__dict__})
        if path == "/subscriptions" and method == "GET":
            user.require("commercial_view")
            from vyonix_commercial.engine import public
            rows = core.engine.subscriptions(search=q.get("search", ""), state=q.get("state") or None)
            return self._send(200, {"items": [public(r) for r in rows], "summary": core.engine.summary()})
        m = re.fullmatch(r"/subscriptions/(\d+)", path)
        if m and method == "GET":
            user.require("commercial_view")
            return self._send(200, core.detail(int(m[1])))
        m = re.fullmatch(r"/subscriptions/(\d+)/([a-z-]+)", path)
        if m and method == "POST":
            return self._send(200, core.action(user, int(m[1]), m[2], json_body(self._body()), ip))
        if path == "/licenses" and method == "POST":
            d = json_body(self._body())
            return self._send(200, core.register_license(
                user, str(d.get("document") or ""), plan_code=d.get("plan_code"), price_cents=d.get("price_cents"),
                customer_document=d.get("customer_document"),
                contract_allows_suspension=d.get("contract_allows_suspension"), auto_suspend=d.get("auto_suspend"),
                ip=ip))
        if path == "/licenses" and method == "GET":
            user.require("commercial_view")
            return self._send(200, {"items": core.licenses()})
        m = re.fullmatch(r"/licenses/([A-Za-z0-9._-]+)/revoke", path)
        if m and method == "POST":
            core.revoke_license(user, m[1], str(json_body(self._body()).get("reason") or ""), ip)
            return self._send(200, {"ok": True})
        if path == "/settings":
            if method == "GET":
                user.require("commercial_view")
                return self._send(200, core.engine.settings())
            if method == "PUT":
                try:
                    core.engine.set_settings(user.actor, json_body(self._body()))
                except Exception as exc:  # noqa: BLE001
                    raise ServerError(400, str(exc)) from exc
                return self._send(200, core.engine.settings())
        if path == "/plans" and method == "GET":
            user.require("commercial_view")
            return self._send(200, {"items": core.engine.plans()})
        m = re.fullmatch(r"/plans/([a-z]+)", path)
        if m and method == "PUT":
            try:
                core.engine.set_plan_price(user.actor, m[1], int(json_body(self._body()).get("price_cents") or 0))
            except Exception as exc:  # noqa: BLE001
                raise ServerError(400, str(exc)) from exc
            return self._send(200, {"items": core.engine.plans()})
        if path == "/evaluate" and method == "POST":
            user.require("commercial_view")
            return self._send(200, core.housekeeping())
        if path == "/audit" and method == "GET":
            return self._send(200, {"items": core.audit(user, int(q.get("limit") or 500)),
                                    "chain_ok": not core.db.verify_audit()})
        if path == "/users":
            if method == "GET":
                return self._send(200, {"items": core.users(user)})
            if method == "POST":
                d = json_body(self._body())
                core.create_user(user, str(d.get("username") or ""), str(d.get("display_name") or ""),
                                 str(d.get("role") or ""), str(d.get("password") or ""))
                return self._send(200, {"ok": True})
        raise ServerError(404, "Não encontrado.")


class Scheduler(threading.Thread):
    """Avalia vencimentos/carências (5 min), consulta cobranças abertas (30 min) e faz a limpeza."""

    def __init__(self, core: ServerCore, *, evaluate_s: float = 300, poll_s: float = 1800) -> None:
        super().__init__(name="vyonix-ls-scheduler", daemon=True)
        self.core, self.evaluate_s, self.poll_s = core, evaluate_s, poll_s
        self.stop = threading.Event()

    def run(self) -> None:
        import time
        last_poll = 0.0
        while not self.stop.is_set():
            try:
                self.core.housekeeping()
                if self.core.provider is not None and time.monotonic() - last_poll >= self.poll_s:
                    last_poll = time.monotonic()
                    self.core.poll_charges()
            except Exception:  # noqa: BLE001
                log.exception("Falha na tarefa periódica")
            finally:
                self.core.db.close()
            self.stop.wait(self.evaluate_s)
