"""Núcleo do VYONIX License Server (sem HTTP): usuários, licenças registradas, autorizações e cobrança."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from vyonix_protocol import formats as F
from vyonix_protocol.crypto import verify_ed25519
from vyonix_commercial.billing.base import BillingError, ChargeRequest
from vyonix_commercial.billing.reconcile import poll_open_charges, process_webhook
from vyonix_commercial.engine import ACTIONS, Actor, CommercialEngine, CommercialError, public, run_action
from vyonix_commercial.engine import ROLES as COM_ROLES
from vyonix_commercial.engine import detail as com_detail

from license_manager.security import check_password, hash_password, validate_password
from license_server.db import Database, iso_now

ROLES = {k: v for k, v in COM_ROLES.items() if k in ("admin", "financial", "support", "viewer")}
MAX_FAILED = 5
LOCK_MINUTES = 15
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")
SERVER_ACTOR = Actor("license-server", "admin")
ACTION_PERMS = {"payment": "payments", "claim": "commercial_view", "grace": "commercial_view",
                "schedule-suspension": "suspend", "cancel-suspension": "suspend", "suspend": "suspend",
                "reactivate": "reactivate", "edit": "subscription_edit"}


class ServerError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class SessionUser:
    id: int
    username: str
    display_name: str
    role: str

    @property
    def actor(self) -> Actor:
        return Actor(self.username, self.role)

    def require(self, perm: str) -> None:
        if perm == "admin_only":
            ok = self.role == "admin"
        else:
            ok = self.actor.can(perm)
        if not ok:
            raise ServerError(403, f"Perfil {ROLES.get(self.role, self.role)} sem permissão para esta operação.")


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_s: float = 60.0) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ServerCore:
    def __init__(self, data_dir: Path, *, signer: tuple[str, Any] | None, license_keys: dict[str, str],
                 license_key_scopes: dict[str, tuple[str, ...]] | None = None, clock: Callable[[], datetime] = utcnow,
                 provider=None, webhook_secret: str = "", session_minutes: int = 30) -> None:
        self.data_dir = Path(data_dir)
        self.db = Database(self.data_dir / "license_server.db")
        self.db.migrate()
        self.signer = signer                        # (key_id, Ed25519PrivateKey)
        self.license_keys = license_keys
        self.license_key_scopes = license_key_scopes or {}
        self.clock = clock
        self.provider = provider
        self.webhook_secret = webhook_secret
        self.session_minutes = session_minutes
        self.limiter = RateLimiter()
        self.engine = CommercialEngine(self.db.conn, self.db.tx, audit=self._audit_hook, clock=lambda: self.clock(),
                                       verify_admin=self.verify_admin, host="server")

    def close(self) -> None:
        self.db.close()

    def _audit_hook(self, actor: str, action: str, target, details, c) -> None:
        self.db.audit(actor, action, target, details, c)

    # ------------------------------------------------------------------ usuários e sessões
    def initialized(self) -> bool:
        return self.db.conn().execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0

    def create_user(self, by: SessionUser | None, username: str, display_name: str, role: str, password: str) -> None:
        if by is None:
            if self.initialized():
                raise ServerError(403, "O servidor já tem usuários: use um administrador.")
            role = "admin"
        else:
            by.require("admin_only")
        if role not in ROLES:
            raise ServerError(400, "Perfil inválido.")
        if not re.fullmatch(r"[A-Za-z0-9._-]{3,40}", username or ""):
            raise ServerError(400, "Usuário inválido (3–40 letras, números, ponto, hífen).")
        try:
            validate_password(password)
        except Exception as exc:  # noqa: BLE001
            raise ServerError(400, str(exc)) from exc
        with self.db.tx() as c:
            if c.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
                raise ServerError(409, "Usuário já existe.")
            c.execute("INSERT INTO users(username, display_name, role, pw_hash, created_at) VALUES (?,?,?,?,?)",
                      (username, display_name or username, role, hash_password(password), iso_now()))
            self.db.audit(by.username if by else username, "user.create", username, {"role": role}, c)

    def users(self, by: SessionUser) -> list[dict]:
        by.require("admin_only")
        return [dict(r) for r in self.db.conn().execute(
            "SELECT id, username, display_name, role, active, created_at, last_login_at FROM users ORDER BY username")]

    def _check_credentials(self, username: str, password: str, ip: str | None) -> dict | None:
        c = self.db.conn()
        r = c.execute("SELECT * FROM users WHERE username = ?", ((username or "").strip(),)).fetchone()
        if r is None or not r["active"]:
            self.db.audit(username or "?", "login.failed", None, {"why": "usuário inexistente/inativo"}, ip=ip)
            return None
        if r["locked_until"] and datetime.fromisoformat(r["locked_until"]) > utcnow():
            raise ServerError(423, "Usuário bloqueado temporariamente por tentativas incorretas.")
        if not check_password(password or "", r["pw_hash"]):
            failed = r["failed"] + 1
            locked = (utcnow() + timedelta(minutes=LOCK_MINUTES)).isoformat() if failed >= MAX_FAILED else None
            c.execute("UPDATE users SET failed = ?, locked_until = ? WHERE id = ?",
                      (0 if locked else failed, locked, r["id"]))
            self.db.audit(username, "login.failed", None, {"locked": bool(locked)}, ip=ip)
            return None
        c.execute("UPDATE users SET failed = 0, locked_until = NULL WHERE id = ?", (r["id"],))
        return dict(r)

    def verify_admin(self, username: str, password: str) -> bool:
        try:
            r = self._check_credentials(username, password, None)
        except ServerError:
            return False
        return bool(r and r["role"] == "admin")

    def login(self, username: str, password: str, ip: str | None) -> tuple[str, SessionUser]:
        if not self.limiter.allow(f"login:{ip}", 10):
            raise ServerError(429, "Muitas tentativas. Aguarde um minuto.")
        r = self._check_credentials(username, password, ip)
        if r is None:
            raise ServerError(401, "Usuário ou senha incorretos.")
        token = secrets.token_urlsafe(32)
        exp = utcnow() + timedelta(minutes=self.session_minutes)
        with self.db.tx() as c:
            c.execute("INSERT INTO sessions(token_hash, user_id, created_at, expires_at, ip) VALUES (?,?,?,?,?)",
                      (hashlib.sha256(token.encode()).hexdigest(), r["id"], iso_now(), exp.isoformat(), ip))
            c.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (iso_now(), r["id"]))
            self.db.audit(r["username"], "login", None, {}, c, ip=ip)
        return token, SessionUser(r["id"], r["username"], r["display_name"], r["role"])

    def session(self, token: str) -> SessionUser:
        if not token:
            raise ServerError(401, "Autenticação necessária.")
        h = hashlib.sha256(token.encode()).hexdigest()
        c = self.db.conn()
        r = c.execute("""SELECT s.expires_at, u.* FROM sessions s JOIN users u ON u.id = s.user_id
                         WHERE s.token_hash = ?""", (h,)).fetchone()
        if r is None or not r["active"] or datetime.fromisoformat(r["expires_at"]) <= utcnow():
            raise ServerError(401, "Sessão expirada ou inválida. Entre novamente.")
        c.execute("UPDATE sessions SET expires_at = ? WHERE token_hash = ?",
                  ((utcnow() + timedelta(minutes=self.session_minutes)).isoformat(), h))
        return SessionUser(r["id"], r["username"], r["display_name"], r["role"])

    def logout(self, token: str) -> None:
        self.db.conn().execute("DELETE FROM sessions WHERE token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),))

    # ------------------------------------------------------------------ licenças registradas
    def _verify_license(self, document: str) -> F.SignedDoc:
        try:
            doc = F.parse_signed(document, F.LICENSE_FORMAT)
        except F.FormatError as exc:
            raise ServerError(400, str(exc)) from exc
        key = self.license_keys.get(doc.key_id)
        if not key or "license" not in self.license_key_scopes.get(doc.key_id, F.ALL_SCOPES):
            raise ServerError(400, f"Licença assinada por chave não reconhecida ({doc.key_id}).")
        if not verify_ed25519(key, doc.signed, doc.signature):
            raise ServerError(400, "Assinatura da licença inválida.")
        errors = F.validate_license_payload(doc.payload)
        if errors or doc.payload.get("product_id") != F.PRODUCT_ID:
            raise ServerError(400, "Licença inválida: " + "; ".join(errors or ["produto"]))
        return doc

    def register_license(self, by: SessionUser, document: str, *, plan_code: str | None = None,
                         price_cents: int | None = None, customer_document: str | None = None,
                         contract_allows_suspension: bool | None = None, auto_suspend: bool | None = None,
                         ip: str | None = None) -> dict:
        by.require("subscription_edit")
        doc = self._verify_license(document)
        p = doc.payload
        if p["type"] == "demo":
            raise ServerError(400, "Demonstrações não são controladas pelo License Server.")
        pol = F.license_policy(p)
        cust = p["customer"]["name"] if isinstance(p.get("customer"), dict) else str(p.get("customer"))
        with self.db.tx() as c:
            c.execute("""INSERT INTO licenses(license_id, document, key_id, customer, type, installation_id, hardware_id,
                             registered_at, registered_by) VALUES (?,?,?,?,?,?,?,?,?)
                         ON CONFLICT(license_id) DO UPDATE SET document = excluded.document""",
                      (p["license_id"], document, doc.key_id, cust, p["type"], p["installation_id"], p["hardware_id"],
                       iso_now(), by.username))
            prev = p.get("reissue_of")
            if prev:
                c.execute("UPDATE licenses SET status = 'replaced' WHERE license_id = ? AND status = 'active'", (prev,))
            self.db.audit(by.username, "license.register", p["license_id"],
                          {"validation": pol["validation"], "reissue_of": prev}, c, ip=ip)
        relink = prev if prev and self.engine.find(prev) else None
        try:
            sub = self.engine.upsert_from_license(
                by.actor, {"license_id": p["license_id"], "type": p["type"], "customer": cust,
                           "customer_document": customer_document, "installation_id": p["installation_id"],
                           "hardware_id": p["hardware_id"], "expires_at": p.get("expires_at"), "policy": p.get("policy")},
                plan_code=plan_code, price_cents=price_cents, relink_from=relink, auto_suspend=auto_suspend,
                contract_allows_suspension=contract_allows_suspension)
        except CommercialError as exc:
            raise ServerError(400, str(exc)) from exc
        out = public(sub)
        if pol["validation"] != "online":
            out["warning"] = "Licença offline: o VYONIX desta clínica não consulta o servidor (use arquivos .vyauth)."
        return out

    def revoke_license(self, by: SessionUser, license_id: str, reason: str, ip: str | None = None) -> None:
        by.require("admin_only")
        if not (reason or "").strip():
            raise ServerError(400, "Informe o motivo da revogação.")
        with self.db.tx() as c:
            if c.execute("UPDATE licenses SET status = 'revoked', revoked_reason = ? WHERE license_id = ?",
                         (reason, license_id)).rowcount != 1:
                raise ServerError(404, "Licença não registrada.")
            self.db.audit(by.username, "license.revoke", license_id, {"reason": reason}, c, ip=ip)

    def licenses(self) -> list[dict]:
        return [dict(r) for r in self.db.conn().execute(
            "SELECT license_id, key_id, customer, type, installation_id, hardware_id, status, revoked_reason, "
            "registered_at, registered_by FROM licenses ORDER BY id DESC")]

    # ------------------------------------------------------------------ autorização (instalações)
    def authorize(self, body: dict, ip: str | None) -> dict:
        if self.signer is None:
            raise ServerError(503, "Servidor sem chave de assinatura carregada.")
        if not self.limiter.allow(f"auth:{ip}", 60):
            raise ServerError(429, "Muitas consultas deste endereço. Tente mais tarde.")
        if not isinstance(body, dict):
            raise ServerError(400, "Consulta inválida.")
        allowed = {"v", "product_id", "license_id", "installation_id", "hardware_id", "nonce", "known_seq",
                   "app_version", "client_time"}
        extra = set(body) - allowed
        if extra:
            raise ServerError(400, "Campos não aceitos: " + ", ".join(sorted(extra)))
        lid, inst, hwid, nonce = (str(body.get(k) or "") for k in ("license_id", "installation_id", "hardware_id",
                                                                     "nonce"))
        if body.get("product_id") != F.PRODUCT_ID or not all(ID_RE.match(x) for x in (lid, inst, hwid)):
            raise ServerError(400, "Consulta inválida.")
        if not NONCE_RE.match(nonce):
            raise ServerError(400, "Número de consulta inválido.")
        if not self.limiter.allow(f"lic:{lid}", 12):
            raise ServerError(429, "Muitas consultas desta licença. Tente mais tarde.")
        c = self.db.conn()
        lic = c.execute("SELECT * FROM licenses WHERE license_id = ?", (lid,)).fetchone()
        if lic is None:
            raise ServerError(404, "Licença não registrada no License Server. Contate o fornecedor.")
        if lic["installation_id"] != inst or lic["hardware_id"] != hwid:
            self.db.audit("instalação", "authorize.mismatch", lid, {"installation_id": inst, "hardware_id": hwid},
                          ip=ip)
            raise ServerError(403, "Instalação ou computador diferente do registrado para esta licença (cópia ou "
                                   "reinstalação). Solicite a reativação ao fornecedor.")
        if lic["status"] == "replaced":
            raise ServerError(409, "Esta licença foi substituída por outra. Instale a licença mais recente.")
        try:
            with self.db.tx() as cc:
                cc.execute("INSERT INTO nonces(nonce, license_id, at) VALUES (?,?,?)", (nonce, lid, iso_now()))
        except Exception as exc:  # noqa: BLE001 - IntegrityError: número repetido
            raise ServerError(409, "Consulta repetida (número de uso único já utilizado).") from exc
        sub = self.engine.find(lid)
        if sub is None:
            raise ServerError(409, "Assinatura não configurada para esta licença.")
        payload = self.engine.build_authorization(SERVER_ACTOR, sub["id"], channel="online", nonce=nonce)
        if lic["status"] == "revoked":
            payload["revoked"] = lic["revoked_reason"] or "revogada"
        key_id, private = self.signer
        document = F.build_signed(F.AUTHORIZATION_FORMAT, payload, key_id, private.sign)
        self.engine.record_authorization(SERVER_ACTOR, payload, document)
        self.engine.record_contact(sub["id"], str(body.get("app_version") or "")[:40])
        return {"authorization": document, "server_time": iso_now()}

    # ------------------------------------------------------------------ autorização offline (arquivo)
    def offline_authorization(self, by: SessionUser, sid: int, ip: str | None = None) -> dict:
        by.require("authorize")
        if self.signer is None:
            raise ServerError(503, "Servidor sem chave de assinatura carregada.")
        try:
            payload = self.engine.build_authorization(by.actor, sid, channel="offline")
        except CommercialError as exc:
            raise ServerError(400, str(exc)) from exc
        key_id, private = self.signer
        document = F.build_signed(F.AUTHORIZATION_FORMAT, payload, key_id, private.sign)
        self.engine.record_authorization(by.actor, payload, document)
        return {"document": document, "authorization_id": payload["authorization_id"]}

    # ------------------------------------------------------------------ gestão comercial
    def detail(self, sid: int) -> dict:
        try:
            return com_detail(self.engine, sid)
        except CommercialError as exc:
            raise ServerError(404, str(exc)) from exc

    def action(self, by: SessionUser, sid: int, name: str, data: dict, ip: str | None = None) -> dict:
        try:
            if name == "charge":
                return self.create_charge(by, sid, data)
            if name == "offline-authorization":
                return self.offline_authorization(by, sid, ip)
            if name not in ACTIONS:
                raise ServerError(404, "Ação desconhecida.")
            by.require(ACTION_PERMS[name])
            return run_action(self.engine, by.actor, sid, name, data, source="manual (servidor)")
        except CommercialError as exc:
            raise ServerError(400, str(exc)) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ServerError(400, f"Dados inválidos: {exc}") from exc

    # ------------------------------------------------------------------ cobrança (opcional)
    def create_charge(self, by: SessionUser, sid: int, data: dict) -> dict:
        by.require("billing")
        if self.provider is None:
            raise ServerError(409, "Nenhuma integração de cobrança configurada (Banco Inter).")
        sub = self.engine.subscription(sid)
        amount = int(data.get("amount_cents") or sub["price_cents"] or 0)
        if amount <= 0:
            raise ServerError(400, "Defina o valor da mensalidade.")
        due = str(data.get("due_date") or "")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due):
            raise ServerError(400, "Vencimento inválido (AAAA-MM-DD).")
        doc = str(data.get("payer_document") or sub.get("customer_document") or "")
        if not doc:
            raise ServerError(400, "Informe o CNPJ/CPF do pagador.")
        req = ChargeRequest(our_number=f"V{sid}{due.replace('-', '')[2:]}", amount_cents=amount, due_date=due,
                            payer_name=str(data.get("payer_name") or sub["customer_name"]), payer_document=doc,
                            payer_email=data.get("payer_email"), payer_address=dict(data.get("payer_address") or {}),
                            message=f"VYONIX DICOM Print — assinatura {sub['license_id']}")
        try:
            ref = self.provider.create_charge(req)
        except BillingError as exc:
            raise ServerError(502, str(exc)) from exc
        return self.engine.register_charge(by.actor, sid, provider=self.provider.name, provider_ref=ref,
                                           amount_cents=amount, due_date=due, periods=int(data.get("periods") or 1),
                                           our_number=req.our_number)

    def webhook(self, provider_name: str, secret: str, body: bytes, ip: str | None) -> dict:
        if self.provider is None or provider_name != self.provider.name:
            raise ServerError(404, "Integração não configurada.")
        if not self.webhook_secret or not secrets.compare_digest(secret, self.webhook_secret):
            self.db.audit("banco", "webhook.denied", provider_name, {}, ip=ip)
            raise ServerError(404, "Não encontrado.")
        if len(body) > 256_000:
            raise ServerError(413, "Notificação muito grande.")
        try:
            out = process_webhook(self.engine, self.provider, body)
        except BillingError as exc:
            raise ServerError(503, f"Consulta ao banco indisponível; reenviar: {exc}") from exc
        self.db.audit("banco", "webhook", provider_name, {"items": out}, ip=ip)
        return {"processed": out}

    def poll_charges(self) -> list[dict]:
        return poll_open_charges(self.engine, self.provider) if self.provider is not None else []

    # ------------------------------------------------------------------ manutenção
    def housekeeping(self) -> dict:
        changes = self.engine.evaluate_all()
        limit = (utcnow() - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.db.tx() as c:
            c.execute("DELETE FROM nonces WHERE at < ?", (limit,))
            c.execute("DELETE FROM sessions WHERE expires_at < ?", (utcnow().isoformat(),))
        return {"changes": changes}

    def audit(self, by: SessionUser, limit: int = 500) -> list[dict]:
        by.require("commercial_view")
        return [dict(r) for r in self.db.conn().execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))]


def load_signer(pem_file: Path, passphrase: str, key_id: str):
    from vyonix_protocol.crypto import private_from_pem
    return key_id, private_from_pem(Path(pem_file).read_bytes(), passphrase.encode())


def json_body(raw: bytes) -> dict:
    try:
        d = json.loads(raw or b"{}")
    except ValueError as exc:
        raise ServerError(400, "JSON inválido.") from exc
    if not isinstance(d, dict):
        raise ServerError(400, "JSON inválido.")
    return d
