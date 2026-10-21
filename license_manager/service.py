"""Núcleo do VYONIX License Manager (sem interface gráfica): usado pela interface e pela linha de comando."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from vyonix_protocol import crypto
from vyonix_protocol import formats as F
from vyonix_protocol.codec import b64d, canonical
from vyonix_commercial.engine import Actor, CommercialEngine, CommercialError

from license_manager import __version__, backup as bk
from license_manager.db import SCHEMA_VERSION, Database
from license_manager.paths import LMPaths
from license_manager.security import (MAX_FAILED, ROLES, AuthError, PermissionDenied, User, check_password,
                                      hash_password, lock_until, validate_password)

UNLOCK_MINUTES = 15
DEFAULT_EDITIONS = ["Profissional", "Clínica", "Rede"]


class LMError(Exception):
    """Erro de operação exibido ao administrador."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return F.iso(utcnow())


@dataclass
class RequestInfo:
    request_id: str
    data: dict[str, Any]
    tpm_status: str                      # verified | absent | invalid | error
    known_installation: dict | None
    related: list[dict]                  # licenças do mesmo computador (comparação de componentes)
    duplicate: bool


class LicenseManager:
    def __init__(self, paths: LMPaths, *, clock=utcnow) -> None:
        self.paths = paths.ensure()
        self.db = Database(paths.db_file)
        self.applied = self.db.migrate()
        self.clock = clock
        self._signer: tuple[float, str, Any] | None = None
        self._lock = threading.Lock()
        self.commercial = CommercialEngine(lambda: self.db.conn(), lambda: self.db.tx(), audit=self._audit_hook,
                                           clock=lambda: self.clock(), verify_admin=self.verify_admin, host="manager")

    def _audit_hook(self, actor: str, action: str, target, details, c) -> None:
        self._audit(actor, action, target, details, c)

    @staticmethod
    def actor(user: User) -> Actor:
        return Actor(user.username, user.role)

    def verify_admin(self, username: str, password: str) -> bool:
        """Confirmação de um administrador comercial (ações comerciais sensíveis)."""
        c = self.db.conn()
        r = c.execute("SELECT * FROM users WHERE username = ?", ((username or "").strip(),)).fetchone()
        if r is None or not r["active"] or r["role"] != "admin":
            self._audit(username or "?", "confirm.failed", None, {"why": "não é administrador ativo"})
            return False
        if r["locked_until"] and datetime.fromisoformat(r["locked_until"]) > utcnow():
            return False
        if not check_password(password or "", r["pw_hash"]):
            failed = r["failed"] + 1
            locked = lock_until().isoformat() if failed >= MAX_FAILED else None
            c.execute("UPDATE users SET failed = ?, locked_until = ? WHERE id = ?",
                      (0 if locked else failed, locked, r["id"]))
            self._audit(username, "confirm.failed", None, {"locked": bool(locked)})
            return False
        c.execute("UPDATE users SET failed = 0 WHERE id = ?", (r["id"],))
        return True

    def close(self) -> None:
        self.lock_key()
        self.db.close()

    # ------------------------------------------------------------------ auditoria (encadeada)
    def _audit(self, actor: str, action: str, target: str | None = None, details: dict | None = None,
               c=None) -> None:
        c = c or self.db.conn()
        prev = c.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
        prev_hash = prev["hash"] if prev else "0" * 64
        at = iso_now()
        det = json.dumps(details or {}, ensure_ascii=False, sort_keys=True)
        h = hashlib.sha256(canonical([prev_hash, at, actor, action, target, det])).hexdigest()
        c.execute("INSERT INTO audit(at, actor, action, target, details, prev_hash, hash) VALUES (?,?,?,?,?,?,?)",
                  (at, actor, action, target, det, prev_hash, h))

    def audit_log(self, limit: int = 500, search: str = "") -> list[dict]:
        q = "SELECT * FROM audit"
        args: list = []
        if search:
            q += " WHERE action LIKE ? OR target LIKE ? OR actor LIKE ? OR details LIKE ?"
            args = [f"%{search}%"] * 4
        q += " ORDER BY id DESC LIMIT ?"
        return [dict(r) for r in self.db.conn().execute(q, (*args, limit))]

    def verify_audit(self) -> list[int]:
        """IDs dos registros cuja cadeia de resumos não confere (alteração fora do aplicativo)."""
        bad, prev = [], "0" * 64
        for r in self.db.conn().execute("SELECT * FROM audit ORDER BY id"):
            h = hashlib.sha256(canonical([prev, r["at"], r["actor"], r["action"], r["target"], r["details"]])).hexdigest()
            if r["prev_hash"] != prev or r["hash"] != h:
                bad.append(r["id"])
            prev = r["hash"]
        return bad

    # ------------------------------------------------------------------ usuários
    def is_initialized(self) -> bool:
        return self.db.conn().execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0

    def initialize(self, username: str, display_name: str, password: str) -> User:
        if self.is_initialized():
            raise LMError("O License Manager já foi configurado.")
        validate_password(password)
        with self.db.tx() as c:
            c.execute("INSERT INTO users(username, display_name, role, pw_hash, created_at) VALUES (?,?,?,?,?)",
                      (username.strip(), display_name.strip() or username, "admin", hash_password(password), iso_now()))
            c.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('created_at', ?)", (iso_now(),))
            c.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('instance_id', ?)", (secrets.token_hex(8),))
            c.execute("""INSERT OR IGNORE INTO products(product_id, name, editions_json, features_json,
                             default_max_devices, default_max_printers, created_at) VALUES (?,?,?,?,?,?,?)""",
                      (F.PRODUCT_ID, F.PRODUCT_NAME, json.dumps(DEFAULT_EDITIONS, ensure_ascii=False),
                       json.dumps(list(F.FEATURES)), 5, 2, iso_now()))
            self._audit(username, "setup", None, {"version": __version__}, c)
        return self.login(username, password)

    def login(self, username: str, password: str) -> User:
        c = self.db.conn()
        r = c.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
        if r is None or not r["active"]:
            self._audit(username or "?", "login.failed", None, {"why": "usuário inexistente ou inativo"})
            raise AuthError("Usuário ou senha incorretos.")
        if r["locked_until"] and datetime.fromisoformat(r["locked_until"]) > utcnow():
            raise AuthError("Usuário bloqueado temporariamente por tentativas incorretas. Tente mais tarde.")
        if not check_password(password, r["pw_hash"]):
            failed = r["failed"] + 1
            locked = lock_until().isoformat() if failed >= MAX_FAILED else None
            c.execute("UPDATE users SET failed = ?, locked_until = ? WHERE id = ?",
                      (0 if locked else failed, locked, r["id"]))
            self._audit(username, "login.failed", None, {"locked": bool(locked)})
            raise AuthError("Usuário ou senha incorretos." + (" Usuário bloqueado por 15 minutos." if locked else ""))
        c.execute("UPDATE users SET failed = 0, locked_until = NULL, last_login_at = ? WHERE id = ?", (iso_now(), r["id"]))
        self._audit(r["username"], "login", None)
        return User(r["id"], r["username"], r["display_name"], r["role"], bool(r["must_change"]))

    def users(self) -> list[dict]:
        return [dict(r) for r in self.db.conn().execute(
            "SELECT id, username, display_name, role, active, must_change, created_at, last_login_at FROM users "
            "ORDER BY username")]

    def create_user(self, user: User, username: str, display_name: str, role: str, password: str) -> None:
        user.require("users")
        if role not in ROLES:
            raise LMError("Papel inválido.")
        validate_password(password)
        try:
            with self.db.tx() as c:
                c.execute("""INSERT INTO users(username, display_name, role, pw_hash, must_change, created_at)
                             VALUES (?,?,?,?,1,?)""", (username.strip(), display_name.strip() or username, role,
                                                       hash_password(password), iso_now()))
                self._audit(user.username, "user.create", username, {"role": role}, c)
        except Exception as exc:  # noqa: BLE001
            if "UNIQUE" in str(exc):
                raise LMError("Já existe um usuário com esse nome.") from exc
            raise

    def update_user(self, user: User, user_id: int, *, role: str | None = None, active: bool | None = None) -> None:
        user.require("users")
        c = self.db.conn()
        target = c.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if target is None:
            raise LMError("Usuário não encontrado.")
        new_role = role or target["role"]
        new_active = target["active"] if active is None else int(active)
        if target["role"] == "admin" and (new_role != "admin" or not new_active):
            admins = c.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1").fetchone()[0]
            if admins <= 1:
                raise LMError("É necessário manter pelo menos um administrador ativo.")
        with self.db.tx() as c:
            c.execute("UPDATE users SET role = ?, active = ? WHERE id = ?", (new_role, new_active, user_id))
            self._audit(user.username, "user.update", target["username"], {"role": new_role, "active": new_active}, c)

    def change_password(self, user: User, old: str, new: str) -> None:
        r = self.db.conn().execute("SELECT pw_hash FROM users WHERE id = ?", (user.id,)).fetchone()
        if not check_password(old, r["pw_hash"]):
            raise AuthError("Senha atual incorreta.")
        validate_password(new)
        with self.db.tx() as c:
            c.execute("UPDATE users SET pw_hash = ?, must_change = 0 WHERE id = ?", (hash_password(new), user.id))
            self._audit(user.username, "user.password", user.username, None, c)

    def reset_password(self, user: User, user_id: int, new: str) -> None:
        user.require("users")
        validate_password(new)
        with self.db.tx() as c:
            name = c.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()["username"]
            c.execute("UPDATE users SET pw_hash = ?, must_change = 1, failed = 0, locked_until = NULL WHERE id = ?",
                      (hash_password(new), user_id))
            self._audit(user.username, "user.reset_password", name, None, c)

    # ------------------------------------------------------------------ chaves de emissão
    def keys(self) -> list[dict]:
        rows = [dict(r) for r in self.db.conn().execute(
            "SELECT key_id, public_hex, status, origin, created_at, note FROM signing_keys ORDER BY id")]
        for r in rows:
            r["fingerprint"] = crypto.fingerprint(r["public_hex"])
            r["licenses"] = self.db.conn().execute("SELECT COUNT(*) FROM licenses WHERE key_id = ?",
                                                   (r["key_id"],)).fetchone()[0]
        return rows

    def active_key(self) -> dict | None:
        r = self.db.conn().execute("SELECT key_id, public_hex FROM signing_keys WHERE status = 'active'").fetchone()
        return dict(r) if r else None

    def _store_key(self, user: User, key_id: str, private, passphrase: str, origin: str, note: str | None) -> dict:
        key_id = key_id.strip()
        if not key_id or len(key_id) > 40 or any(ch.isspace() for ch in key_id):
            raise LMError("Identificador da chave inválido (sem espaços, até 40 caracteres).")
        try:
            pem = crypto.private_to_pem(private, passphrase.encode("utf-8"))
        except ValueError as exc:
            raise LMError(str(exc)) from exc
        pub = crypto.public_hex(private)
        status = "standby" if self.active_key() else "active"
        try:
            with self.db.tx() as c:
                c.execute("""INSERT INTO signing_keys(key_id, public_hex, private_pem, status, origin, created_at, note)
                             VALUES (?,?,?,?,?,?,?)""", (key_id, pub, pem, status, origin, iso_now(), note))
                self._audit(user.username, f"key.{origin}", key_id, {"fingerprint": crypto.fingerprint(pub),
                                                                    "status": status}, c)
        except Exception as exc:  # noqa: BLE001
            if "UNIQUE" in str(exc):
                raise LMError("Já existe uma chave com esse identificador ou com a mesma chave pública.") from exc
            raise
        return {"key_id": key_id, "public_hex": pub, "status": status, "fingerprint": crypto.fingerprint(pub)}

    def generate_key(self, user: User, key_id: str, passphrase: str, note: str | None = None) -> dict:
        user.require("keys")
        return self._store_key(user, key_id, crypto.generate_ed25519(), passphrase, "generated", note)

    def import_key(self, user: User, key_id: str, pem: bytes, passphrase: str, note: str | None = None) -> dict:
        user.require("keys")
        try:
            private = crypto.private_from_pem(pem, passphrase.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise LMError("Não foi possível abrir a chave: frase-senha incorreta ou arquivo inválido.") from exc
        return self._store_key(user, key_id, private, passphrase, "imported", note)

    def set_key_status(self, user: User, key_id: str, status: str) -> None:
        user.require("keys")
        if status not in ("active", "standby", "retired"):
            raise LMError("Situação inválida.")
        with self.db.tx() as c:
            if status == "active":
                c.execute("UPDATE signing_keys SET status = 'standby' WHERE status = 'active'")
            c.execute("UPDATE signing_keys SET status = ? WHERE key_id = ?", (status, key_id))
            self._audit(user.username, "key.status", key_id, {"status": status}, c)
        self.lock_key()

    def export_public_line(self, key_id: str) -> str:
        r = self.db.conn().execute("SELECT public_hex FROM signing_keys WHERE key_id = ?", (key_id,)).fetchone()
        if r is None:
            raise LMError("Chave não encontrada.")
        return (f'    # {key_id} — impressão digital {crypto.fingerprint(r["public_hex"])}\n'
                f'    "{key_id}": "{r["public_hex"]}",\n')

    def export_key_backup(self, user: User, key_id: str, passphrase: str, dest: Path) -> Path:
        """Backup protegido da chave: PKCS#8 cifrado (a frase-senha é conferida antes)."""
        user.require("keys")
        r = self.db.conn().execute("SELECT * FROM signing_keys WHERE key_id = ?", (key_id,)).fetchone()
        if r is None:
            raise LMError("Chave não encontrada.")
        try:
            crypto.private_from_pem(bytes(r["private_pem"]), passphrase.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise LMError("Frase-senha incorreta.") from exc
        dest = Path(dest)
        dest.write_bytes(bytes(r["private_pem"]))
        self._audit(user.username, "key.backup", key_id, {"file": dest.name})
        return dest

    def change_key_passphrase(self, user: User, key_id: str, old: str, new: str) -> None:
        user.require("keys")
        r = self.db.conn().execute("SELECT private_pem FROM signing_keys WHERE key_id = ?", (key_id,)).fetchone()
        try:
            private = crypto.private_from_pem(bytes(r["private_pem"]), old.encode("utf-8"))
            pem = crypto.private_to_pem(private, new.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise LMError("Frase-senha atual incorreta ou nova frase-senha curta demais.") from exc
        with self.db.tx() as c:
            c.execute("UPDATE signing_keys SET private_pem = ? WHERE key_id = ?", (pem, key_id))
            self._audit(user.username, "key.passphrase", key_id, None, c)
        self.lock_key()

    def unlock_key(self, user: User, passphrase: str) -> str:
        user.require("issue")
        r = self.db.conn().execute("SELECT key_id, private_pem FROM signing_keys WHERE status = 'active'").fetchone()
        if r is None:
            raise LMError("Nenhuma chave de emissão ativa. Gere ou importe uma em Segurança → Chaves de emissão.")
        try:
            private = crypto.private_from_pem(bytes(r["private_pem"]), passphrase.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            self._audit(user.username, "key.unlock_failed", r["key_id"])
            raise LMError("Frase-senha da chave incorreta.") from exc
        with self._lock:
            self._signer = (time.monotonic() + UNLOCK_MINUTES * 60, r["key_id"], private)
        self._audit(user.username, "key.unlock", r["key_id"])
        return r["key_id"]

    def lock_key(self) -> None:
        with self._lock:
            self._signer = None

    def key_unlocked(self) -> str | None:
        with self._lock:
            s = self._signer
            if s and time.monotonic() < s[0]:
                return s[1]
            self._signer = None
            return None

    def _sign_doc(self, fmt: str, payload: dict) -> tuple[str, str]:
        with self._lock:
            s = self._signer
            if not s or time.monotonic() >= s[0]:
                self._signer = None
                raise LMError("Desbloqueie a chave de emissão (frase-senha) antes de emitir.")
            key_id, private = s[1], s[2]
        return key_id, F.build_signed(fmt, payload, key_id, private.sign)

    # ------------------------------------------------------------------ clientes e produtos
    def customers(self, search: str = "", include_inactive: bool = False) -> list[dict]:
        q = """SELECT c.*, (SELECT COUNT(*) FROM licenses l WHERE l.customer_id = c.id AND l.status = 'active')
                      AS active_licenses FROM customers c WHERE 1=1"""
        args: list = []
        if not include_inactive:
            q += " AND c.active = 1"
        if search:
            q += " AND (c.name LIKE ? OR c.document LIKE ? OR c.city LIKE ? OR c.email LIKE ?)"
            args += [f"%{search}%"] * 4
        return [dict(r) for r in self.db.conn().execute(q + " ORDER BY c.name", args)]

    def customer(self, cid: int) -> dict:
        r = self.db.conn().execute("SELECT * FROM customers WHERE id = ?", (cid,)).fetchone()
        if r is None:
            raise LMError("Cliente não encontrado.")
        return dict(r)

    CUSTOMER_FIELDS = ("name", "document", "contact", "email", "phone", "city", "state", "notes")

    def save_customer(self, user: User, data: dict, cid: int | None = None) -> int:
        user.require("customers")
        vals = {k: (str(data.get(k) or "").strip() or None) for k in self.CUSTOMER_FIELDS}
        if not vals["name"]:
            raise LMError("Informe o nome do cliente.")
        with self.db.tx() as c:
            if cid is None:
                cur = c.execute(f"""INSERT INTO customers({", ".join(vals)}, created_at, updated_at)
                                    VALUES ({", ".join("?" * len(vals))}, ?, ?)""", (*vals.values(), iso_now(), iso_now()))
                cid = cur.lastrowid
                self._audit(user.username, "customer.create", vals["name"], {"id": cid}, c)
            else:
                c.execute(f"""UPDATE customers SET {", ".join(f"{k} = ?" for k in vals)}, updated_at = ? WHERE id = ?""",
                          (*vals.values(), iso_now(), cid))
                self._audit(user.username, "customer.update", vals["name"], {"id": cid}, c)
        return int(cid)

    def anonymize_customer(self, user: User, cid: int) -> None:
        """LGPD: remove os dados pessoais e mantém o histórico técnico das licenças."""
        user.require("anonymize")
        with self.db.tx() as c:
            c.execute("""UPDATE customers SET name = ?, document = NULL, contact = NULL, email = NULL, phone = NULL,
                            city = NULL, state = NULL, notes = NULL, active = 0, anonymized_at = ?, updated_at = ?
                         WHERE id = ?""", (f"Cliente anonimizado #{cid}", iso_now(), iso_now(), cid))
            c.execute("UPDATE requests SET site = NULL WHERE customer_id = ?", (cid,))
            c.execute("UPDATE installations SET site = NULL WHERE customer_id = ?", (cid,))
            self._audit(user.username, "customer.anonymize", str(cid), None, c)

    def customer_history(self, cid: int) -> dict:
        c = self.db.conn()
        return {
            "licenses": [dict(r) for r in c.execute(
                """SELECT license_id, type, edition, status, hardware_id, installation_id, issued_at, expires_at,
                          operation, reissue_of, reason_code, reason_text, created_by FROM licenses
                   WHERE customer_id = ? ORDER BY id DESC""", (cid,))],
            "installations": [dict(r) for r in c.execute(
                "SELECT * FROM installations WHERE customer_id = ? ORDER BY id DESC", (cid,))],
            "reactivations": [dict(r) for r in c.execute(
                "SELECT * FROM reactivations WHERE customer_id = ? ORDER BY id DESC", (cid,))],
        }

    def products(self) -> list[dict]:
        out = []
        for r in self.db.conn().execute("SELECT * FROM products ORDER BY name"):
            d = dict(r)
            d["editions"] = json.loads(d.pop("editions_json"))
            d["features"] = json.loads(d.pop("features_json"))
            out.append(d)
        return out

    def product(self, product_id: str) -> dict:
        for p in self.products():
            if p["product_id"] == product_id:
                return p
        raise LMError(f"Produto não cadastrado: {product_id}.")

    def save_product(self, user: User, product_id: str, name: str, editions: list[str], features: list[str],
                     max_devices: int | None, max_printers: int | None, active: bool = True) -> None:
        user.require("products")
        if product_id != F.PRODUCT_ID:
            raise LMError("Somente o produto VYONIX DICOM Print é suportado pelo protocolo de licença atual.")
        bad = [f for f in features if f not in F.FEATURES]
        if bad or not editions:
            raise LMError("Recursos inválidos ou nenhuma edição informada.")
        with self.db.tx() as c:
            c.execute("""INSERT INTO products(product_id, name, editions_json, features_json, default_max_devices,
                             default_max_printers, active, created_at) VALUES (?,?,?,?,?,?,?,?)
                         ON CONFLICT(product_id) DO UPDATE SET name = excluded.name, editions_json = excluded.editions_json,
                             features_json = excluded.features_json, default_max_devices = excluded.default_max_devices,
                             default_max_printers = excluded.default_max_printers, active = excluded.active""",
                      (product_id, name, json.dumps(editions, ensure_ascii=False), json.dumps(features), max_devices,
                       max_printers, int(active), iso_now()))
            self._audit(user.username, "product.save", product_id, {"editions": editions, "features": features}, c)

    # ------------------------------------------------------------------ solicitações
    def import_request(self, user: User, text: str) -> RequestInfo:
        user.require("issue")
        try:
            data = F.parse_request(text)
        except F.FormatError as exc:
            raise LMError(str(exc)) from exc
        tpm_status = "absent"
        tpm = data.get("tpm")
        if isinstance(tpm, dict) and tpm.get("pub"):
            try:
                pub = b64d(tpm["pub"])
                ok = bool(tpm.get("sig")) and crypto.verify_tpm(
                    tpm["alg"], pub, hashlib.sha256(F.request_signed_part(data)).digest(), b64d(tpm["sig"]))
                ok = ok and crypto.tpm_key_digest(tpm["alg"], pub) == (data["hw"].get("tpm") or "")
                tpm_status = "verified" if ok else ("error" if tpm.get("error") else "invalid")
            except Exception:  # noqa: BLE001
                tpm_status = "invalid"
        c = self.db.conn()
        dup = c.execute("SELECT id FROM requests WHERE request_id = ?", (data["request_id"],)).fetchone() is not None
        known = c.execute("SELECT * FROM installations WHERE hardware_id = ? AND installation_id = ?",
                          (data["hardware_id"], data["installation_id"])).fetchone()
        if not dup:
            with self.db.tx() as cc:
                cc.execute("""INSERT INTO requests(request_id, raw, hardware_id, installation_id, hw_json, tpm_status,
                                  app_version, site, reason, previous_license_id, demo_used, requested_at, imported_at,
                                  imported_by, customer_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                           (data["request_id"], F.encode_request(data), data["hardware_id"], data["installation_id"],
                            json.dumps(data["hw"]), tpm_status, data.get("app_version"), data.get("site"),
                            data.get("reason"), data.get("previous_license_id"), int(bool(data.get("demo_used"))),
                            data.get("requested_at"), iso_now(), user.username,
                            known["customer_id"] if known else None))
                self._audit(user.username, "request.import", data["request_id"],
                            {"hardware_id": data["hardware_id"], "installation_id": data["installation_id"],
                             "tpm": tpm_status, "reason": data.get("reason")}, cc)
        return RequestInfo(data["request_id"], data, tpm_status, dict(known) if known else None,
                           self.related_licenses(data["hw"], data["hardware_id"]), dup)

    def related_licenses(self, hw: dict, hardware_id: str | None = None) -> list[dict]:
        """Licenças já emitidas para o mesmo computador (componentes em comum) ou o mesmo Hardware ID."""
        out = []
        for r in self.db.conn().execute(
                """SELECT l.*, c.name AS customer FROM licenses l JOIN customers c ON c.id = l.customer_id
                   ORDER BY l.id DESC"""):
            lhw = json.loads(r["hw_json"])
            m = F.compare_hardware(lhw, hw)
            common = len(m.matched)
            if r["hardware_id"] == hardware_id or m.ok or common >= 2:
                d = dict(r)
                d["match"] = "mesmo computador" if (m.ok or r["hardware_id"] == hardware_id) else \
                    f"{common} componente(s) em comum; alterado(s): " + ", ".join(F.HW_LABELS[x] for x in m.changed)
                out.append(d)
        return out

    def requests(self, limit: int = 200) -> list[dict]:
        return [dict(r) for r in self.db.conn().execute(
            """SELECT r.*, c.name AS customer FROM requests r LEFT JOIN customers c ON c.id = r.customer_id
               ORDER BY r.id DESC LIMIT ?""", (limit,))]

    def request_data(self, request_id: str) -> dict:
        r = self.db.conn().execute("SELECT raw FROM requests WHERE request_id = ?", (request_id,)).fetchone()
        if r is None:
            raise LMError("Solicitação não encontrada (importe-a primeiro).")
        return F.parse_request(r["raw"])

    # ------------------------------------------------------------------ licenças
    def _new_license_id(self) -> str:
        return f"VYX-{utcnow():%Y}-{secrets.token_hex(4).upper()}"

    def demo_history(self, hw: dict, hardware_id: str) -> list[dict]:
        return [r for r in self.related_licenses(hw, hardware_id) if r["type"] == "demo" and r["match"] == "mesmo computador"]

    def _issue(self, user: User, *, customer_id: int, product_id: str, edition: str, ltype: str, hw: dict,
               hardware_id: str, installation_id: str, starts: datetime | None, custom_end: datetime | None,
               max_devices: int | None, max_printers: int | None, features: list[str], notes: str | None,
               operation: str, request_id: str | None, reissue_of: str | None, reason_code: str | None,
               reason_text: str | None, demo_override: str | None = None,
               expiry_base: datetime | None = None, validation: str = "offline", price_cents: int | None = None,
               contract_allows_suspension: bool | None = None, auto_suspend: bool | None = None) -> dict:
        user.require("issue")
        if ltype not in F.LICENSE_TYPES:
            raise LMError("Tipo de licença inválido.")
        prod = self.product(product_id)
        if edition not in prod["editions"]:
            raise LMError(f"Edição inválida para {prod['name']}.")
        features = [f for f in F.FEATURES if f in features]
        if not features:
            raise LMError("Selecione pelo menos um recurso.")
        for label, v in (("equipamentos", max_devices), ("impressoras", max_printers)):
            if v is not None and (int(v) < 1 or int(v) > 999):
                raise LMError(f"Quantidade de {label} deve estar entre 1 e 999 (ou ilimitada).")
        self.customer(customer_id)
        if ltype == "demo":
            prev = self.demo_history(hw, hardware_id)
            if prev and not (demo_override and demo_override.strip()):
                raise LMError("Este computador já recebeu DEMO ("
                              + ", ".join(p["license_id"] for p in prev) + "). Informe a justificativa para emitir "
                              "outra demonstração.")
        issued = self.clock()
        start = starts or issued
        try:
            expires = F.compute_expiry(ltype, expiry_base or start, custom_end)
        except ValueError as exc:
            raise LMError(str(exc)) from exc
        if expires is not None and expires <= start:
            raise LMError("A data de vencimento deve ser posterior ao início.")
        duration = None
        if ltype == "demo":
            duration = F.DEMO_HOURS
            expires = issued + timedelta(days=F.DEMO_ACTIVATE_WITHIN_DAYS)     # prazo para ativar a DEMO
        cust = self.customer(customer_id)
        lid = self._new_license_id()
        payload = {
            "v": F.VERSION, "license_id": lid, "product_id": product_id, "product": prod["name"], "type": ltype,
            "edition": edition, "customer": {"name": cust["name"]},
            "hardware_id": hardware_id, "hw": hw, "installation_id": installation_id,
            "issued_at": F.iso(issued), "starts_at": F.iso(start), "expires_at": F.iso(expires) if expires else None,
            "duration_hours": duration, "max_devices": max_devices, "max_printers": max_printers,
            "features": features, "request_id": request_id, "reissue_of": reissue_of,
        }
        if ltype != "demo":
            try:
                payload["policy"] = self.commercial.policy_for_license(validation)
            except CommercialError as exc:
                raise LMError(str(exc)) from exc
        errors = F.validate_license_payload(payload)
        if errors:
            raise LMError("Dados da licença inválidos: " + "; ".join(errors))
        key_id, document = self._sign_doc(F.LICENSE_FORMAT, payload)
        with self.db.tx() as c:
            c.execute("""INSERT INTO licenses(license_id, customer_id, product_id, edition, type, hardware_id,
                             installation_id, hw_json, issued_at, starts_at, expires_at, duration_hours, max_devices,
                             max_printers, features_json, notes, status, key_id, document, request_id, reissue_of,
                             operation, reason_code, reason_text, created_by)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active',?,?,?,?,?,?,?,?)""",
                      (lid, customer_id, product_id, edition, ltype, hardware_id, installation_id, json.dumps(hw),
                       payload["issued_at"], payload["starts_at"], payload["expires_at"], duration, max_devices,
                       max_printers, json.dumps(features), notes, key_id, document, request_id, reissue_of, operation,
                       reason_code, reason_text or demo_override, user.username))
            c.execute("""INSERT INTO installations(customer_id, hardware_id, installation_id, hw_json, first_seen,
                             last_license_id) VALUES (?,?,?,?,?,?)
                         ON CONFLICT(hardware_id, installation_id) DO UPDATE SET last_license_id = excluded.last_license_id,
                             customer_id = excluded.customer_id""",
                      (customer_id, hardware_id, installation_id, json.dumps(hw), iso_now(), lid))
            if request_id:
                c.execute("UPDATE requests SET customer_id = ? WHERE request_id = ?", (customer_id, request_id))
            self._audit(user.username, f"license.{operation}", lid,
                        {"customer_id": customer_id, "type": ltype, "edition": edition, "hardware_id": hardware_id,
                         "installation_id": installation_id, "expires_at": payload["expires_at"], "key_id": key_id,
                         "features": features, "max_devices": max_devices, "max_printers": max_printers,
                         "reissue_of": reissue_of, "reason": reason_code, "demo_override": demo_override,
                         "policy": payload.get("policy")}, c)
        if ltype != "demo":
            try:
                self.commercial.upsert_from_license(
                    self.actor(user),
                    {"license_id": lid, "type": ltype, "customer": cust["name"], "customer_document": cust["document"],
                     "customer_ref": str(customer_id), "installation_id": installation_id, "hardware_id": hardware_id,
                     "expires_at": payload["expires_at"], "policy": payload["policy"]},
                    relink_from=reissue_of, price_cents=price_cents, auto_suspend=auto_suspend,
                    contract_allows_suspension=contract_allows_suspension,
                    extend_paid=operation in ("issue", "renew"))
            except CommercialError as exc:
                raise LMError(f"Licença {lid} emitida, mas a assinatura não foi registrada: {exc}") from exc
        return self.license(lid)

    def license_policy(self, license_id: str) -> dict:
        lic = self.license(license_id)
        return F.license_policy(F.parse_signed(lic["document"], F.LICENSE_FORMAT).payload)

    # ------------------------------------------------------------------ gestão comercial (offline)
    def offline_authorization(self, user: User, license_id: str) -> dict:
        """Arquivo de renovação/autorização (.vyauth) assinado com a chave do License Manager."""
        user.require("view")
        try:
            sub = self.commercial.subscription(license_id)
            payload = self.commercial.build_authorization(self.actor(user), sub["id"], channel="offline")
        except CommercialError as exc:
            raise LMError(str(exc)) from exc
        _key, doc = self._sign_doc(F.AUTHORIZATION_FORMAT, payload)
        self.commercial.record_authorization(self.actor(user), payload, doc)
        return {"payload": payload, "document": doc}

    def issue(self, user: User, request_id: str, customer_id: int, *, ltype: str, edition: str,
              product_id: str = F.PRODUCT_ID, starts: datetime | None = None, custom_end: datetime | None = None,
              max_devices: int | None = None, max_printers: int | None = None, features: list[str] | None = None,
              notes: str | None = None, demo_override: str | None = None, validation: str = "offline",
              price_cents: int | None = None, contract_allows_suspension: bool | None = None,
              auto_suspend: bool | None = None) -> dict:
        req = self.request_data(request_id)
        active = self.db.conn().execute(
            "SELECT license_id FROM licenses WHERE installation_id = ? AND hardware_id = ? AND status = 'active'",
            (req["installation_id"], req["hardware_id"])).fetchone()
        if active and self.license(active["license_id"])["type"] != "demo":
            raise LMError(f"Esta instalação já tem a licença ativa {active['license_id']}. Use Renovar "
                          "(mesma instalação) ou Reativar (nova instalação/computador).")
        new = self._issue(user, customer_id=customer_id, product_id=product_id, edition=edition, ltype=ltype,
                           hw=req["hw"], hardware_id=req["hardware_id"], installation_id=req["installation_id"],
                           starts=starts, custom_end=custom_end, max_devices=max_devices, max_printers=max_printers,
                           features=features if features is not None else list(F.FEATURES), notes=notes,
                           operation="demo" if ltype == "demo" else "issue", request_id=request_id,
                           reissue_of=active["license_id"] if active else None,
                           reason_code=None, reason_text=None, demo_override=demo_override, validation=validation,
                           price_cents=price_cents, contract_allows_suspension=contract_allows_suspension,
                           auto_suspend=auto_suspend)
        if active:
            with self.db.tx() as c:
                c.execute("UPDATE licenses SET status = 'superseded' WHERE license_id = ?", (active["license_id"],))
        return new

    def renew(self, user: User, license_id: str, *, ltype: str, starts: datetime | None = None,
              custom_end: datetime | None = None, edition: str | None = None, max_devices: int | None = -1,
              max_printers: int | None = -1, features: list[str] | None = None, notes: str | None = None,
              validation: str | None = None) -> dict:
        old = self.license(license_id)
        if old["status"] in ("revoked", "replaced"):
            raise LMError("Licença revogada ou substituída não pode ser renovada.")
        base = None
        if old["expires_at"] and old["type"] != "demo":
            prev_end = F.parse_time(old["expires_at"])
            if prev_end > self.clock():
                base = prev_end + timedelta(seconds=1)      # renovação antecipada: o novo período soma ao atual
        new = self._issue(user, customer_id=old["customer_id"], product_id=old["product_id"],
                          edition=edition or old["edition"], ltype=ltype, hw=old["hw"], hardware_id=old["hardware_id"],
                          installation_id=old["installation_id"], starts=starts, custom_end=custom_end,
                          max_devices=old["max_devices"] if max_devices == -1 else max_devices,
                          max_printers=old["max_printers"] if max_printers == -1 else max_printers,
                          features=features if features is not None else old["features"], notes=notes,
                          operation="renew", request_id=None, reissue_of=license_id, reason_code="renewal",
                          reason_text=None, expiry_base=base,
                          validation=validation or self._validation_of(old))
        with self.db.tx() as c:
            c.execute("UPDATE licenses SET status = 'superseded' WHERE license_id = ?", (license_id,))
        return new

    def _validation_of(self, lic: dict) -> str:
        try:
            pol = F.parse_signed(lic["document"], F.LICENSE_FORMAT).payload.get("policy")
        except F.FormatError:
            pol = None
        return (pol or {}).get("validation") or "offline"

    def reactivate(self, user: User, old_license_id: str, request_id: str, reason_code: str, reason_text: str, *,
                   ltype: str | None = None, starts: datetime | None = None, custom_end: datetime | None = None,
                   keep_validity: bool = True) -> dict:
        """REATIVAR / EMITIR NOVA LICENÇA: nova instalação ou computador do mesmo cliente."""
        if reason_code not in F.REACTIVATION_REASONS:
            raise LMError("Selecione o motivo da reativação.")
        if not (reason_text or "").strip():
            raise LMError("Descreva o motivo da reativação (fica no histórico do cliente).")
        old = self.license(old_license_id)
        if old["status"] == "revoked":
            raise LMError("A licença anterior foi revogada; emita uma licença nova se for o caso.")
        req = self.request_data(request_id)
        if req["installation_id"] == old["installation_id"] and req["hardware_id"] == old["hardware_id"]:
            raise LMError("A solicitação é da mesma instalação da licença anterior: use Renovar.")
        ltype = ltype or old["type"]
        if keep_validity and ltype == old["type"] and old["expires_at"] and ltype not in ("demo", "permanent"):
            ltype, custom_end = "custom", F.parse_time(old["expires_at"])
            starts = starts or self.clock()
        new = self._issue(user, customer_id=old["customer_id"], product_id=old["product_id"], edition=old["edition"],
                          ltype=ltype, hw=req["hw"], hardware_id=req["hardware_id"],
                          installation_id=req["installation_id"], starts=starts, custom_end=custom_end,
                          max_devices=old["max_devices"], max_printers=old["max_printers"], features=old["features"],
                          notes=old["notes"], operation="reactivate", request_id=request_id, reissue_of=old_license_id,
                          reason_code=reason_code, reason_text=reason_text,
                          demo_override="reativação" if ltype == "demo" else None,
                          validation=self._validation_of(old))
        with self.db.tx() as c:
            if old["status"] == "active":
                c.execute("UPDATE licenses SET status = 'replaced' WHERE license_id = ?", (old_license_id,))
            c.execute("""INSERT INTO reactivations(customer_id, old_license_id, new_license_id, reason_code, reason_text,
                             old_hardware_id, new_hardware_id, actor, at) VALUES (?,?,?,?,?,?,?,?,?)""",
                      (old["customer_id"], old_license_id, new["license_id"], reason_code, reason_text,
                       old["hardware_id"], req["hardware_id"], user.username, iso_now()))
        return new

    def revoke(self, user: User, license_id: str, reason: str) -> None:
        user.require("revoke")
        if not (reason or "").strip():
            raise LMError("Informe o motivo da revogação.")
        lic = self.license(license_id)
        if lic["status"] == "revoked":
            return
        with self.db.tx() as c:
            c.execute("UPDATE licenses SET status = 'revoked', revoked_at = ?, revoked_reason = ? WHERE license_id = ?",
                      (iso_now(), reason, license_id))
            self._audit(user.username, "license.revoke", license_id, {"reason": reason}, c)

    def revocation_list(self, user: User) -> dict:
        """Lista de revogação assinada para instalar nos computadores (efeito somente quando instalada)."""
        user.require("revoke")
        c = self.db.conn()
        seq = (c.execute("SELECT MAX(seq) FROM revocation_lists").fetchone()[0] or 0) + 1
        revoked = [{"license_id": r["license_id"], "at": r["revoked_at"], "reason": r["revoked_reason"]}
                   for r in c.execute("SELECT license_id, revoked_at, revoked_reason FROM licenses "
                                      "WHERE status = 'revoked' ORDER BY id")]
        payload = {"v": F.VERSION, "product_id": F.PRODUCT_ID, "seq": seq, "issued_at": iso_now(), "revoked": revoked}
        _key, doc = self._sign_doc(F.REVOCATION_FORMAT, payload)
        with self.db.tx() as cc:
            cc.execute("INSERT INTO revocation_lists(seq, issued_at, count, document, actor) VALUES (?,?,?,?,?)",
                       (seq, payload["issued_at"], len(revoked), doc, user.username))
            self._audit(user.username, "revocation.list", str(seq), {"count": len(revoked)}, cc)
        return {"seq": seq, "count": len(revoked), "document": doc}

    def licenses(self, *, status: str | None = None, search: str = "", customer_id: int | None = None,
                 expiring_days: int | None = None) -> list[dict]:
        q = """SELECT l.*, c.name AS customer FROM licenses l JOIN customers c ON c.id = l.customer_id WHERE 1=1"""
        args: list = []
        if status:
            q += " AND l.status = ?"
            args.append(status)
        if customer_id:
            q += " AND l.customer_id = ?"
            args.append(customer_id)
        if search:
            q += " AND (l.license_id LIKE ? OR c.name LIKE ? OR l.hardware_id LIKE ? OR l.installation_id LIKE ?)"
            args += [f"%{search}%"] * 4
        rows = [self._row(r) for r in self.db.conn().execute(q + " ORDER BY l.id DESC", args)]
        if expiring_days is not None:
            lim = self.clock() + timedelta(days=expiring_days)
            rows = [r for r in rows if r["expires_at"] and r["type"] != "demo" and r["status"] == "active"
                    and self.clock() < F.parse_time(r["expires_at"]) <= lim]
        return rows

    def _row(self, r) -> dict:
        d = dict(r)
        d["hw"] = json.loads(d.pop("hw_json"))
        d["features"] = json.loads(d.pop("features_json"))
        d["type_label"] = F.LICENSE_TYPES[d["type"]][0]
        exp = F.parse_time(d["expires_at"]) if d["expires_at"] else None
        d["expired"] = bool(exp and exp <= self.clock() and d["type"] != "demo")
        return d

    def license(self, license_id: str) -> dict:
        r = self.db.conn().execute("""SELECT l.*, c.name AS customer FROM licenses l JOIN customers c
                                      ON c.id = l.customer_id WHERE l.license_id = ?""", (license_id,)).fetchone()
        if r is None:
            raise LMError(f"Licença não encontrada: {license_id}.")
        return self._row(r)

    def export_license(self, user: User, license_id: str, dest: Path) -> Path:
        user.require("view")
        lic = self.license(license_id)
        dest = Path(dest)
        dest.write_text(lic["document"], encoding="utf-8")
        self._audit(user.username, "license.export", license_id, {"file": dest.name})
        return dest

    # ------------------------------------------------------------------ revalidação de horário/integridade
    def read_diagnostic(self, text: str) -> dict:
        try:
            d = json.loads(text)
        except ValueError as exc:
            raise LMError("Arquivo de diagnóstico ilegível.") from exc
        if d.get("format") != F.DIAGNOSTIC_FORMAT or d.get("product_id") != F.PRODUCT_ID:
            raise LMError("O arquivo não é um diagnóstico do VYONIX DICOM Print.")
        for k in ("request_id", "hardware_id", "hw", "installation_id"):
            if not d.get(k):
                raise LMError(f"Diagnóstico incompleto ({k}).")
        if F.hardware_id(d["hw"]) != d["hardware_id"]:
            raise LMError("Diagnóstico inconsistente (Hardware ID).")
        return d

    def revalidate(self, user: User, diagnostic_text: str, *, reason: str, actions: list[str],
                   trusted_time: datetime | None = None) -> dict:
        user.require("revalidate")
        d = self.read_diagnostic(diagnostic_text)
        if not reason.strip():
            raise LMError("Informe o motivo da revalidação.")
        actions = [a for a in actions if a in ("time", "integrity")] or ["time"]
        c = self.db.conn()
        if c.execute("SELECT 1 FROM revalidations WHERE request_id = ?", (d["request_id"],)).fetchone():
            raise LMError("Este diagnóstico já foi revalidado.")
        inst = c.execute("SELECT customer_id FROM installations WHERE installation_id = ?",
                         (d["installation_id"],)).fetchone()
        payload = {"v": F.VERSION, "product_id": F.PRODUCT_ID, "kind": "revalidation", "request_id": d["request_id"],
                   "hardware_id": d["hardware_id"], "hw": d["hw"], "installation_id": d["installation_id"],
                   "issued_at": iso_now(), "trusted_time": F.iso(trusted_time or self.clock()), "actions": actions,
                   "reason": reason, "issued_by": user.username}
        _key, doc = self._sign_doc(F.REVALIDATION_FORMAT, payload)
        with self.db.tx() as cc:
            cc.execute("""INSERT INTO revalidations(request_id, customer_id, hardware_id, installation_id, diagnostic,
                              actions, reason, document, actor, at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                       (d["request_id"], inst["customer_id"] if inst else None, d["hardware_id"], d["installation_id"],
                        diagnostic_text, json.dumps(actions), reason, doc, user.username, iso_now()))
            self._audit(user.username, "revalidation", d["request_id"],
                        {"installation_id": d["installation_id"], "actions": actions, "reason": reason,
                         "time_issue": (d.get("time") or {}).get("issue")}, cc)
        return {"request_id": d["request_id"], "document": doc}

    # ------------------------------------------------------------------ painel
    def dashboard(self) -> dict:
        c = self.db.conn()

        def n(sql: str, *a) -> int:
            return int(c.execute(sql, a).fetchone()[0])
        lic = self.licenses()
        active = [x for x in lic if x["status"] == "active"]
        return {
            "customers": n("SELECT COUNT(*) FROM customers WHERE active = 1"),
            "licenses_active": len([x for x in active if not x["expired"] and x["type"] != "demo"]),
            "demos": len([x for x in active if x["type"] == "demo"]),
            "expiring_30": len(self.licenses(expiring_days=30)),
            "expired": len([x for x in active if x["expired"]]),
            "revoked": n("SELECT COUNT(*) FROM licenses WHERE status = 'revoked'"),
            "permanent": len([x for x in active if x["type"] == "permanent"]),
            "requests_pending": n("""SELECT COUNT(*) FROM requests r WHERE NOT EXISTS
                                     (SELECT 1 FROM licenses l WHERE l.request_id = r.request_id)"""),
            "reactivations": n("SELECT COUNT(*) FROM reactivations"),
            "key": self.active_key(),
            "audit_ok": not self.verify_audit(),
            "recent": self.audit_log(12),
            "expiring": self.licenses(expiring_days=30)[:20],
        }

    # ------------------------------------------------------------------ backup e restauração
    def backup(self, user: User, dest: Path, passphrase: str) -> Path:
        user.require("backup")
        data = bk.snapshot(self.paths.db_file)
        blob = bk.encrypt(data, passphrase, {"app": "VYONIX License Manager", "app_version": __version__,
                                             "schema": SCHEMA_VERSION})
        dest = Path(dest)
        dest.write_bytes(blob)
        self._audit(user.username, "backup", dest.name, {"bytes": len(blob)})
        return dest

    def auto_backup(self, keep: int = 10) -> Path | None:
        """Cópia local automática (mesma pasta protegida do banco), uma por dia."""
        folder = self.paths.backups_dir / "automaticos"
        folder.mkdir(parents=True, exist_ok=True)
        today = folder / f"license_manager-{utcnow():%Y%m%d}.db"
        if today.exists() or not self.paths.db_file.exists():
            return None
        today.write_bytes(bk.snapshot(self.paths.db_file))
        for old in sorted(folder.glob("license_manager-*.db"))[:-keep]:
            old.unlink()
        return today

    def restore(self, user: User, src: Path, passphrase: str) -> dict:
        """Substitui o banco pelo do backup (o atual é guardado). Requer reabrir o aplicativo."""
        user.require("restore")
        header, data = bk.decrypt(Path(src).read_bytes(), passphrase)
        schema = bk.verify_sqlite(data)
        if schema > SCHEMA_VERSION:
            raise LMError("Backup de uma versão mais nova do License Manager.")
        self._audit(user.username, "restore", Path(src).name, {"created_at": header.get("created_at")})
        self.lock_key()
        self.db.close()
        keep = self.paths.backups_dir / f"antes-da-restauracao-{utcnow():%Y%m%d-%H%M%S}.db"
        if self.paths.db_file.exists():
            shutil.copy2(self.paths.db_file, keep)
        for suffix in ("-wal", "-shm"):
            p = Path(str(self.paths.db_file) + suffix)
            if p.exists():
                p.unlink()
        tmp = self.paths.db_file.with_suffix(".restaurando")
        tmp.write_bytes(data)
        os.replace(tmp, self.paths.db_file)
        self.db = Database(self.paths.db_file)
        self.db.migrate()
        self._audit(user.username, "restore.done", Path(src).name, {"previous_saved_as": keep.name})
        return header


__all__ = ["LicenseManager", "LMError", "AuthError", "PermissionDenied", "RequestInfo", "User"]
