"""Servidor HTTPS do VYONIX Reception (rede local).

* HTTPS com certificado próprio gerado no primeiro uso (``<dados>/reception/tls``); pode ser
  substituído por um certificado da instituição (``cert.pem`` + ``key.pem``).
* Somente endereços locais/privados por padrão (``reception.allow_public`` desligado) — não expor à
  internet. A regra do Firewall do Windows do VYONIX vale para redes privadas e de domínio.
* Login com usuário e senha (perfis), sessão com cookie ``HttpOnly; Secure; SameSite=Strict``,
  expiração por inatividade, token anti-CSRF em toda ação, cabeçalhos de segurança, auditoria.
"""

from __future__ import annotations

import base64
import hashlib
import io
import ipaddress
import json
import logging
import mimetypes
import re
import secrets
import socket
import ssl
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.core.errors import ValidationError
from app.reception.exams import PICKUP_STATES, PRINT_STATES, DuplicatePrint
from app.security.users import ROLES, AuthError
from app.utils.timeutil import from_iso, to_iso, utc_now, utc_now_iso

log = logging.getLogger("vyonix.reception")
COOKIE = "vyx_session"


def ensure_certificate(folder: Path) -> tuple[Path, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    cert, key = folder / "cert.pem", folder / "key.pem"
    if cert.exists() and key.exists():
        return cert, key
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    from app.utils.net import local_ipv4_addresses
    k = ec.generate_private_key(ec.SECP256R1())
    host = socket.gethostname()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"VYONIX Reception ({host})"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "VYONIX")])
    alt = [x509.DNSName(host), x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    for ip in local_ipv4_addresses():
        alt.append(x509.IPAddress(ipaddress.ip_address(ip)))
    now = datetime.now(timezone.utc)
    c = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
         .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
         .not_valid_after(now + timedelta(days=1825)).add_extension(x509.SubjectAlternativeName(alt), False)
         .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
         .sign(k, hashes.SHA256()))
    key.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()))
    cert.write_bytes(c.public_bytes(serialization.Encoding.PEM))
    return cert, key


def _allowed_source(address: str, allow_public: bool) -> bool:
    if allow_public:
        return True
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_private or ip.is_loopback or ip.is_link_local


class ReceptionServer:
    def __init__(self, *, db, events, settings_get, users, exams, worker, printers, devices_repo,
                 static_dir: Path, tls_dir: Path) -> None:
        self.db = db
        self.events = events
        self.get = settings_get
        self.users = users
        self.exams = exams
        self.worker = worker
        self.printers = printers
        self.devices = devices_repo
        self.static_dir = Path(static_dir)
        self.tls_dir = Path(tls_dir)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.url: str | None = None
        self.error: str | None = None

    # ------------------------------------------------------------------ ciclo de vida
    def start(self) -> None:
        if self._httpd is not None or not self.get("reception.enabled"):
            return
        address, port = self.get("reception.bind_address"), int(self.get("reception.port"))
        try:
            cert, key = ensure_certificate(self.tls_dir)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.load_cert_chain(str(cert), str(key))
            httpd = ThreadingHTTPServer((address, port), _handler_for(self))
            httpd.daemon_threads = True
            httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        except OSError as exc:
            self.error = f"porta {port} indisponível ({exc})"
            self.events.add(level="ERROR", category="system", action="reception.start_failed",
                            message=f"VYONIX Reception não iniciou: {self.error}", actor="system")
            return
        self._httpd = httpd
        self._thread = threading.Thread(target=httpd.serve_forever, name="vyonix-reception", daemon=True)
        self._thread.start()
        self.url = f"https://{self.public_host()}:{port}/"
        self.error = None
        self.events.add(level="INFO", category="system", action="reception.start",
                        message=f"VYONIX Reception em {self.url}", actor="system")

    def stop(self) -> None:
        httpd, self._httpd = self._httpd, None
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()

    @property
    def running(self) -> bool:
        return self._httpd is not None

    def bound_port(self) -> int | None:
        return self._httpd.server_address[1] if self._httpd else None

    def public_host(self) -> str:
        from app.utils.net import best_server_address
        ip, _ = best_server_address(self.get("reception.bind_address"))
        return ip or "localhost"

    # ------------------------------------------------------------------ sessões
    def new_session(self, user, address: str) -> tuple[str, str]:
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        exp = to_iso(utc_now() + timedelta(minutes=int(self.get("reception.session_minutes"))))
        conn = self.db.connection()
        conn.execute("DELETE FROM web_sessions WHERE expires_at < ?", (utc_now_iso(),))
        conn.execute("INSERT INTO web_sessions(token_hash, user_id, csrf, created_at, expires_at, address) "
                     "VALUES (?,?,?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), user.id, csrf,
                                              utc_now_iso(), exp, address))
        return token, csrf

    def session(self, token: str | None):
        if not token:
            return None, None
        h = hashlib.sha256(token.encode()).hexdigest()
        conn = self.db.connection()
        r = conn.execute("SELECT * FROM web_sessions WHERE token_hash = ?", (h,)).fetchone()
        if r is None or from_iso(r["expires_at"]) < utc_now():
            if r is not None:
                conn.execute("DELETE FROM web_sessions WHERE token_hash = ?", (h,))
            return None, None
        user = self.users.get(r["user_id"])
        if user is None:
            return None, None
        conn.execute("UPDATE web_sessions SET expires_at = ? WHERE token_hash = ?",
                     (to_iso(utc_now() + timedelta(minutes=int(self.get("reception.session_minutes")))), h))
        return user, r["csrf"]

    def end_session(self, token: str | None) -> None:
        if token:
            self.db.connection().execute("DELETE FROM web_sessions WHERE token_hash = ?",
                                         (hashlib.sha256(token.encode()).hexdigest(),))


def _handler_for(srv: ReceptionServer):
    class Handler(BaseHTTPRequestHandler):
        server_version = "VYONIX-Reception"
        sys_version = ""

        def log_message(self, fmt, *args):  # noqa: D401 - silencioso (auditoria própria)
            log.debug("%s %s", self.address_string(), fmt % args)

        # ---------------------------------------------------------- utilitários
        def _headers(self, status: int, ctype: str, length: int, extra: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Strict-Transport-Security", "max-age=31536000")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; "
                                                        "style-src 'self'; script-src 'self'; frame-ancestors 'none'")
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()

        def _json(self, status: int, obj: Any, extra: dict | None = None) -> None:
            body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
            self._headers(status, "application/json; charset=utf-8", len(body), extra)
            self.wfile.write(body)

        def _cookie(self) -> str | None:
            for part in (self.headers.get("Cookie") or "").split(";"):
                k, _, v = part.strip().partition("=")
                if k == COOKIE:
                    return v
            return None

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 64 * 1024:
                raise ValidationError("Requisição grande demais.")
            raw = self.rfile.read(n) if n else b"{}"
            try:
                data = json.loads(raw or b"{}")
            except ValueError as exc:
                raise ValidationError("JSON inválido.") from exc
            return data if isinstance(data, dict) else {}

        def _guard(self) -> bool:
            if not _allowed_source(self.client_address[0], bool(srv.get("reception.allow_public"))):
                self._json(403, {"error": "Acesso permitido somente pela rede local."})
                srv.events.add(level="WARNING", category="security", action="reception.blocked_ip",
                               message=f"Acesso ao VYONIX Reception recusado de {self.client_address[0]}.",
                               actor="system")
                return False
            return True

        def _auth(self, *, write: bool):
            user, csrf = srv.session(self._cookie())
            if user is None:
                self._json(401, {"error": "Sessão expirada. Entre novamente."})
                return None
            if write and not secrets.compare_digest(self.headers.get("X-CSRF-Token") or "", csrf):
                self._json(403, {"error": "Token de segurança inválido. Recarregue a página."})
                return None
            return user

        def _done(self) -> None:
            try:
                srv.db.close_thread_connection()
            except Exception:  # noqa: BLE001
                pass

        # ---------------------------------------------------------- GET
        def do_GET(self) -> None:  # noqa: N802
            try:
                if not self._guard():
                    return
                url = urlparse(self.path)
                if not url.path.startswith("/api/"):
                    return self._static(url.path)
                user = self._auth(write=False)
                if user is None:
                    return
                q = {k: v[0] for k, v in parse_qs(url.query).items()}
                self._route_get(url.path, q, user)
            except ValidationError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                log.exception("Erro no VYONIX Reception")
                self._json(500, {"error": f"Erro interno: {type(exc).__name__}"})
            finally:
                self._done()

        def _static(self, path: str) -> None:
            name = "index.html" if path in ("/", "") else path.lstrip("/")
            if not re.fullmatch(r"[A-Za-z0-9_.\-]+", name):
                return self._json(404, {"error": "não encontrado"})
            f = srv.static_dir / name
            if not f.is_file():
                return self._json(404, {"error": "não encontrado"})
            data = f.read_bytes()
            ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript",):
                ctype += "; charset=utf-8"
            self._headers(200, ctype, len(data))
            self.wfile.write(data)

        def _route_get(self, path: str, q: dict, user) -> None:
            if path == "/api/me":
                return self._json(200, {**user.public(), "csrf": srv.session(self._cookie())[1]})
            if path == "/api/meta":
                rules = [{"id": d.id, "name": d.name} for d in srv.devices.list()]
                notice = srv.exams.license_reason() if srv.exams.license_reason else None
                return self._json(200, {"print_states": PRINT_STATES, "pickup_states": PICKUP_STATES,
                                        "rules": rules, "roles": ROLES, "license_notice": notice})
            if path == "/api/exams":
                user.require("reception")
                res = srv.exams.search(q=q.get("q", ""), modality=q.get("modality") or None,
                                       device_id=int(q["rule"]) if q.get("rule") else None,
                                       date_from=q.get("from") or None, date_to=q.get("to") or None,
                                       print_state=q.get("print_state") or None,
                                       pickup_state=q.get("pickup_state") or None,
                                       limit=min(int(q.get("limit") or 200), 1000))
                return self._json(200, res)
            m = re.fullmatch(r"/api/exams/(\d+)", path)
            if m:
                user.require("reception")
                srv.exams.log_view(int(m[1]), user)
                d = srv.exams.detail(int(m[1]))
                d["last_print"] = srv.exams.last_print(d["jobs"])
                return self._json(200, d)
            m = re.fullmatch(r"/api/exams/(\d+)/preview", path)
            if m:
                user.require("reception")
                return self._json(200, self._preview(int(m[1])))
            if path == "/api/printers":
                names = [p.name for p in srv.printers.list() if p.available] if srv.printers else []
                return self._json(200, {"printers": names})
            if path == "/api/alerts":
                return self._json(200, {"alerts": srv.exams.alerts()})
            if path == "/api/reports":
                user.require("reports")
                rep = srv.exams.report(group=q.get("group", "modality"), date_from=q.get("from") or None,
                                       date_to=q.get("to") or None)
                if q.get("format") == "csv":
                    return self._csv(rep)
                return self._json(200, rep)
            self._json(404, {"error": "não encontrado"})

        def _csv(self, rep: dict) -> None:
            import csv
            buf = io.StringIO()
            w = csv.writer(buf, delimiter=";")
            cols = ["chave", "exames", "trabalhos", "folhas_enviadas", "folhas_confirmadas", "reimpressoes", "falhas"]
            w.writerow(cols)
            for r in rep["rows"]:
                w.writerow([r.get(c) for c in cols])
            w.writerow([])
            w.writerow(["economia estimada (sob demanda)", rep["saved_estimate"]["exams"], "exames",
                        rep["saved_estimate"]["sheets"], "folhas"])
            data = ("﻿" + buf.getvalue()).encode("utf-8")
            self._headers(200, "text/csv; charset=utf-8", len(data),
                          {"Content-Disposition": f'attachment; filename="vyonix-relatorio-{rep["group"]}.csv"'})
            self.wfile.write(data)

        def _preview(self, exam_id: int) -> dict:
            from PIL import Image
            d = srv.exams.detail(exam_id)
            base = [j for j in d["jobs"] if j["source_type"] in ("storage", "dicom_print") and not j["parent_job_id"]]
            pages, warnings = [], []
            for j in base:
                try:
                    pp, ww = srv.worker.preview(j["id"], max_pages=4)
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"Trabalho #{j['id']}: {exc}")
                    continue
                warnings += ww
                for p in pp:
                    img = Image.fromarray(p.pixels)
                    img.thumbnail((900, 1270))
                    out = io.BytesIO()
                    img.save(out, "PNG", optimize=True)
                    pages.append("data:image/png;base64," + base64.b64encode(out.getvalue()).decode())
                if len(pages) >= 8:
                    break
            return {"pages": pages, "warnings": warnings}

        # ---------------------------------------------------------- POST
        def do_POST(self) -> None:  # noqa: N802
            try:
                if not self._guard():
                    return
                path = urlparse(self.path).path
                if path == "/api/login":
                    return self._login()
                user = self._auth(write=True)
                if user is None:
                    return
                data = self._body()
                self._route_post(path, data, user)
            except DuplicatePrint as exc:
                self._json(409, {"error": str(exc), "duplicate": True, "last": exc.last})
            except (ValidationError, AuthError) as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                log.exception("Erro no VYONIX Reception")
                self._json(500, {"error": f"Erro interno: {type(exc).__name__}"})
            finally:
                self._done()

        def _login(self) -> None:
            data = self._body()
            try:
                user = srv.users.authenticate(str(data.get("username", "")), str(data.get("password", "")),
                                              address=self.client_address[0])
            except AuthError as exc:
                return self._json(401, {"error": str(exc)})
            user.require("reception")
            token, csrf = srv.new_session(user, self.client_address[0])
            self._json(200, {**user.public(), "csrf": csrf},
                       {"Set-Cookie": f"{COOKIE}={token}; HttpOnly; Secure; SameSite=Strict; Path=/"})

        def _route_post(self, path: str, data: dict, user) -> None:
            if path == "/api/logout":
                srv.end_session(self._cookie())
                return self._json(200, {"ok": True},
                                  {"Set-Cookie": f"{COOKIE}=; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=0"})
            if path == "/api/password":
                from app.security.users import check_password
                r = srv.db.connection().execute("SELECT pw_hash FROM users WHERE id = ?", (user.id,)).fetchone()
                if not check_password(str(data.get("old", "")), r["pw_hash"]):
                    raise ValidationError("Senha atual incorreta.")
                srv.users.set_password(user.id, str(data.get("new", "")), actor=user.actor, must_change=False)
                return self._json(200, {"ok": True})
            m = re.fullmatch(r"/api/exams/(\d+)/(print|print-now|pickup)", path)
            if not m:
                return self._json(404, {"error": "não encontrado"})
            exam_id, action = int(m[1]), m[2]
            key = str(data.get("request_key") or "")[:80] or None
            if action in ("print", "print-now"):
                res = srv.exams.print_exam(
                    exam_id, user, request_key=key, confirm_duplicate=bool(data.get("confirm_duplicate")),
                    reason=(data.get("reason") or None), printer=(data.get("printer") or None) if action == "print-now"
                    else None, copies=int(data["copies"]) if action == "print-now" and data.get("copies") else None,
                    now=action == "print-now")
                return self._json(200, res)
            res = srv.exams.set_pickup(exam_id, user, str(data.get("state", "")), note=data.get("note") or None,
                                       delivered_to=data.get("delivered_to") or None, request_key=key)
            self._json(200, res)

    return Handler
