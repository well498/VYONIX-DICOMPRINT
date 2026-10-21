"""Gestão Comercial do License Manager: a mesma interface para as assinaturas deste License Manager
(clientes offline, arquivos de renovação assinados com a chave do License Manager) e para as do
VYONIX License Server (clientes online, administração remota pela API HTTPS autenticada)."""

from __future__ import annotations

import hashlib
import http.client
import json
import ssl
import urllib.parse
from typing import Any

from vyonix_commercial.engine import CommercialError, detail, public, run_action

from license_manager.service import LicenseManager, LMError


class LocalCommercial:
    remote = False

    def __init__(self, lm: LicenseManager, user) -> None:
        self.lm, self.user = lm, user
        self.label = "Este License Manager (assinaturas offline)"

    @property
    def engine(self):
        return self.lm.commercial

    def _a(self):
        return self.lm.actor(self.user)

    def subscriptions(self, search: str = "", state: str | None = None) -> list[dict]:
        self.user.require("view")
        return [public(r) for r in self.engine.subscriptions(search=search, state=state)]

    def summary(self) -> dict:
        return self.engine.summary()

    def detail(self, sid: int) -> dict:
        return detail(self.engine, sid)

    def action(self, sid: int, name: str, data: dict) -> dict:
        if name == "offline-authorization":
            sub = self.engine.subscription(sid)
            return {"document": self.lm.offline_authorization(self.user, sub["license_id"])["document"]}
        return run_action(self.engine, self._a(), sid, name, data, source="manual (License Manager)")

    def settings(self) -> dict:
        return self.engine.settings()

    def set_settings(self, values: dict) -> dict:
        self.engine.set_settings(self._a(), values)
        return self.engine.settings()

    def plans(self) -> list[dict]:
        return self.engine.plans()

    def set_plan_price(self, code: str, cents: int) -> None:
        self.engine.set_plan_price(self._a(), code, cents)

    def evaluate(self) -> dict:
        return {"changes": self.engine.evaluate_all()}


class RemoteError(Exception):
    pass


class RemoteCommercial:
    """Cliente da API administrativa do VYONIX License Server."""

    remote = True

    def __init__(self, url: str, *, pin: str | None = None, ca_file: str | None = None, timeout: float = 20) -> None:
        u = urllib.parse.urlsplit(url.strip())
        if u.scheme != "https" or not u.hostname:
            raise RemoteError("Endereço do License Server inválido (use https://servidor:porta).")
        self.host, self.port, self.base = u.hostname, u.port or 443, (u.path.rstrip("/") or "")
        self.pin = (pin or "").replace(":", "").lower() or None
        self.ca_file = ca_file or None
        self.timeout = timeout
        self.token: str | None = None
        self.user: dict | None = None
        self.label = f"License Server {self.host}:{self.port}"

    def _ctx(self) -> ssl.SSLContext:
        if self.pin:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE                 # conferido pela impressão digital abaixo
        else:
            ctx = ssl.create_default_context(cafile=self.ca_file)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        return ctx

    def _req(self, method: str, path: str, body: dict | None = None) -> Any:
        c = http.client.HTTPSConnection(self.host, self.port, timeout=self.timeout, context=self._ctx())
        try:
            c.connect()
            if self.pin:
                der = c.sock.getpeercert(binary_form=True) or b""
                if hashlib.sha256(der).hexdigest() != self.pin:
                    raise RemoteError("O certificado do servidor não corresponde à impressão digital configurada.")
            h = {"Content-Type": "application/json"}
            if self.token:
                h["Authorization"] = f"Bearer {self.token}"
            c.request(method, self.base + "/v1/admin" + path,
                      body=json.dumps(body, default=str).encode() if body is not None else None, headers=h)
            r = c.getresponse()
            data = json.loads(r.read() or b"{}")
        except (OSError, ssl.SSLError, http.client.HTTPException, ValueError) as exc:
            raise RemoteError(f"License Server indisponível: {exc}") from exc
        finally:
            c.close()
        if r.status >= 400:
            raise RemoteError(data.get("error") or f"HTTP {r.status}")
        return data

    def login(self, username: str, password: str) -> dict:
        d = self._req("POST", "/login", {"username": username, "password": password})
        self.token, self.user = d["token"], d["user"]
        return d["user"]

    def subscriptions(self, search: str = "", state: str | None = None) -> list[dict]:
        q = urllib.parse.urlencode({k: v for k, v in {"search": search, "state": state}.items() if v})
        return self._req("GET", "/subscriptions" + (f"?{q}" if q else ""))["items"]

    def summary(self) -> dict:
        return self._req("GET", "/subscriptions")["summary"]

    def detail(self, sid: int) -> dict:
        return self._req("GET", f"/subscriptions/{int(sid)}")

    def action(self, sid: int, name: str, data: dict) -> dict:
        return self._req("POST", f"/subscriptions/{int(sid)}/{name}", data)

    def settings(self) -> dict:
        return self._req("GET", "/settings")

    def set_settings(self, values: dict) -> dict:
        return self._req("PUT", "/settings", values)

    def plans(self) -> list[dict]:
        return self._req("GET", "/plans")["items"]

    def set_plan_price(self, code: str, cents: int) -> None:
        self._req("PUT", f"/plans/{code}", {"price_cents": int(cents)})

    def evaluate(self) -> dict:
        return self._req("POST", "/evaluate", {})

    def register_license(self, document: str, *, plan_code: str | None = None, price_cents: int | None = None,
                         customer_document: str | None = None) -> dict:
        return self._req("POST", "/licenses", {"document": document, "plan_code": plan_code,
                                               "price_cents": price_cents, "customer_document": customer_document})

    def audit(self, limit: int = 300) -> dict:
        return self._req("GET", f"/audit?limit={int(limit)}")

    def logout(self) -> None:
        if self.token:
            try:
                self._req("POST", "/logout", {})
            except RemoteError:
                pass
        self.token = None


def as_error(exc: Exception) -> str:
    if isinstance(exc, (CommercialError, LMError, RemoteError)):
        return str(exc)
    return f"{type(exc).__name__}: {exc}"
