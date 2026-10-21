"""Gestão comercial das assinaturas: pagamentos, carência, suspensão controlada, reativação e
autorizações de uso. Mesmo código no License Manager (offline) e no License Server (online).

Regras de negócio aplicadas aqui (e não na interface):

* boleto emitido, comprovante enviado ou promessa de pagamento **não** quitam: só ``confirm_payment``
  (operador financeiro ou conciliação bancária confirmada por consulta ao banco) altera o período pago;
* a suspensão exige: inadimplência confirmada, avisos registrados para o vencimento, fim da carência,
  contrato que a preveja, licença não permanente e a confirmação de que os requisitos operacionais da
  clínica foram verificados; as ações listadas em ``confirm_actions`` exigem a confirmação de um
  administrador comercial diferente do operador;
* toda mudança fica no histórico (estado anterior, novo estado, responsável, origem e motivo).
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from vyonix_protocol import formats as F

from vyonix_commercial.schema import DEFAULT_PLANS, DEFAULT_SETTINGS, statements
from vyonix_commercial.states import (SNAPSHOT_KEYS, CommercialState, Evaluation, evaluate, grace_end, iso, local,
                                      parse)

ROLES = {"admin": "Administrador comercial", "financial": "Operador financeiro", "support": "Suporte técnico",
         "issuer": "Emissor de licenças", "viewer": "Consulta"}
PERMS = {
    "commercial_view": {"admin", "financial", "support", "issuer", "viewer"},
    "payments": {"admin", "financial"},
    "subscription_edit": {"admin", "financial"},
    "suspend": {"admin", "financial"},
    "reactivate": {"admin", "financial"},
    "authorize": {"admin", "financial", "support", "issuer"},
    "commercial_settings": {"admin"},
    "billing": {"admin", "financial"},
}
ACTION_LABELS = {
    "create": "Assinatura registrada", "relink": "Licença substituída (renovação/reativação)",
    "payment": "Pagamento confirmado", "payment_duplicate": "Confirmação de pagamento repetida (ignorada)",
    "payment_claim": "Comprovante/promessa registrado (não quita)", "charge": "Cobrança emitida",
    "charge_status": "Situação da cobrança", "grace": "Carência prorrogada",
    "schedule_suspension": "Suspensão programada", "cancel_suspension": "Suspensão cancelada",
    "suspend": "Suspensão aplicada", "reactivate": "Reativação", "state": "Mudança de estado",
    "authorization": "Autorização emitida", "edit": "Dados da assinatura alterados", "contact": "Contato do VYONIX",
}


class CommercialError(Exception):
    """Operação comercial recusada (mensagem para o operador)."""


@dataclass(frozen=True)
class Actor:
    username: str
    role: str

    def can(self, perm: str) -> bool:
        return self.role in PERMS.get(perm, set())


SYSTEM = Actor("sistema", "admin")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CommercialEngine:
    def __init__(self, conn: Callable[[], sqlite3.Connection],
                 tx: Callable[[], AbstractContextManager[sqlite3.Connection]], *,
                 audit: Callable[..., None] | None = None, clock: Callable[[], datetime] = utcnow,
                 verify_admin: Callable[[str, str], bool] | None = None, host: str = "manager") -> None:
        self.conn = conn
        self.tx = tx
        self._audit = audit
        self.clock = clock
        self.verify_admin = verify_admin
        self.host = host                       # manager | server (origem das autorizações)

    # ------------------------------------------------------------------ esquema
    @staticmethod
    def install_schema(c: sqlite3.Connection) -> None:
        for stmt in statements():
            c.execute(stmt)
        for k, v in DEFAULT_SETTINGS.items():
            c.execute("INSERT OR IGNORE INTO com_settings(key, value) VALUES (?, ?)", (k, v))
        for code, name, months in DEFAULT_PLANS:
            c.execute("INSERT OR IGNORE INTO com_plans(code, name, months) VALUES (?, ?, ?)", (code, name, months))

    # ------------------------------------------------------------------ utilidades
    def now(self) -> datetime:
        return self.clock().astimezone(timezone.utc)

    def audit(self, actor: Actor, action: str, target: str | None, details: dict, c) -> None:
        if self._audit:
            self._audit(actor.username, f"commercial.{action}", target, details, c)

    @staticmethod
    def _require(actor: Actor, perm: str) -> None:
        if not actor.can(perm):
            raise CommercialError(f"O perfil {ROLES.get(actor.role, actor.role)} não pode executar esta operação.")

    def settings(self) -> dict[str, str]:
        out = dict(DEFAULT_SETTINGS)
        out.update({r["key"]: r["value"] for r in self.conn().execute("SELECT key, value FROM com_settings")})
        return out

    def setting_int(self, key: str) -> int:
        try:
            return int(self.settings().get(key) or 0)
        except ValueError:
            return int(DEFAULT_SETTINGS[key])

    def set_settings(self, actor: Actor, values: dict[str, Any]) -> None:
        self._require(actor, "commercial_settings")
        clean: dict[str, str] = {}
        for k, v in values.items():
            if k not in DEFAULT_SETTINGS:
                raise CommercialError(f"Parâmetro desconhecido: {k}.")
            if k in ("warn_days", "grace_days", "max_grace_extension_days", "auth_ttl_days", "online_tolerance_days"):
                n = int(v)
                lim = {"auth_ttl_days": (1, 90), "online_tolerance_days": (0, 90)}.get(k, (0, 365))
                if not lim[0] <= n <= lim[1]:
                    raise CommercialError(f"{k}: valor fora do intervalo {lim[0]}–{lim[1]}.")
                v = n
            elif k == "auto_suspend":
                v = 1 if v in (True, 1, "1", "true", "sim") else 0
            elif k in ("grace_roles", "confirm_actions"):
                items = [x.strip() for x in (v if isinstance(v, (list, tuple)) else str(v).split(",")) if x.strip()]
                allowed = ROLES if k == "grace_roles" else {"suspend", "schedule_suspension", "reactivate", "grace",
                                                            "payment"}
                bad = [x for x in items if x not in allowed]
                if bad:
                    raise CommercialError(f"{k}: valores inválidos ({', '.join(bad)}).")
                v = ",".join(items)
            elif k == "server_url" and v and not str(v).startswith("https://"):
                raise CommercialError("O endereço do License Server deve começar com https://.")
            clean[k] = str(v if v is not None else "")
        with self.tx() as c:
            for k, v in clean.items():
                c.execute("INSERT INTO com_settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = "
                          "excluded.value", (k, v))
            self.audit(actor, "settings", None, clean, c)

    def policy_for_license(self, validation: str = "offline") -> dict[str, Any]:
        """Política assinada na licença (o VYONIX não consegue alterá-la)."""
        s = self.settings()
        if validation == "online" and not s.get("server_url"):
            raise CommercialError("Validação online: configure antes o endereço do License Server (Políticas "
                                  "comerciais).")
        return {"validation": validation, "warn_days": int(s["warn_days"]), "grace_days": int(s["grace_days"]),
                "online_tolerance_days": int(s["online_tolerance_days"]),
                "server_url": (s.get("server_url") or None) if validation == "online" else None,
                "server_pin": (s.get("server_pin") or None) if validation == "online" else None}

    def plans(self) -> list[dict]:
        return [dict(r) for r in self.conn().execute("SELECT * FROM com_plans ORDER BY COALESCE(months, 999), code")]

    def set_plan_price(self, actor: Actor, code: str, price_cents: int) -> None:
        self._require(actor, "subscription_edit")
        if price_cents < 0:
            raise CommercialError("Valor inválido.")
        with self.tx() as c:
            if c.execute("UPDATE com_plans SET price_cents = ? WHERE code = ?", (int(price_cents), code)).rowcount != 1:
                raise CommercialError("Plano desconhecido.")
            self.audit(actor, "plan_price", code, {"price_cents": price_cents}, c)

    # ------------------------------------------------------------------ assinaturas
    def _row(self, r) -> dict[str, Any]:
        d = dict(r)
        ev = evaluate(self.snapshot(d), self.now())
        d["evaluation"] = ev
        d["state"] = ev.state.value
        d["state_label"] = ev.label
        d["days_overdue"] = ev.days_overdue
        d["grace_until"] = iso(ev.grace_until)
        plan = self.conn().execute("SELECT name, months FROM com_plans WHERE code = ?", (d["plan_code"],)).fetchone()
        d["plan_name"] = plan["name"] if plan else d["plan_code"]
        d["plan_months"] = plan["months"] if plan else None
        return d

    def snapshot(self, sub: dict[str, Any]) -> dict[str, Any]:
        snap = {k: sub.get(k) for k in SNAPSHOT_KEYS if k != "plan"}
        snap["permanent"] = bool(sub.get("permanent"))
        snap["auto_suspend"] = bool(sub.get("auto_suspend"))
        snap["plan"] = sub.get("plan_code")
        return snap

    def subscription(self, key: int | str) -> dict[str, Any]:
        col = "id" if isinstance(key, int) else "license_id"
        r = self.conn().execute(f"SELECT * FROM com_subscriptions WHERE {col} = ?", (key,)).fetchone()
        if r is None:
            raise CommercialError(f"Assinatura não encontrada: {key}.")
        return self._row(r)

    def find(self, license_id: str) -> dict[str, Any] | None:
        r = self.conn().execute("SELECT * FROM com_subscriptions WHERE license_id = ?", (license_id,)).fetchone()
        return self._row(r) if r else None

    def subscriptions(self, *, search: str = "", state: str | None = None, include_inactive: bool = False) -> list[dict]:
        q, args = "SELECT * FROM com_subscriptions WHERE 1=1", []
        if not include_inactive:
            q += " AND active = 1"
        if search:
            q += (" AND (customer_name LIKE ? OR customer_document LIKE ? OR license_id LIKE ? OR installation_id LIKE ?"
                  " OR hardware_id LIKE ?)")
            args += [f"%{search}%"] * 5
        rows = [self._row(r) for r in self.conn().execute(q + " ORDER BY customer_name, id", args)]
        return [r for r in rows if state is None or r["state"] == state]

    def upsert_from_license(self, actor: Actor, lic: dict[str, Any], *, plan_code: str | None = None,
                            price_cents: int | None = None, relink_from: str | None = None,
                            contract_allows_suspension: bool | None = None, auto_suspend: bool | None = None,
                            operational_notes: str | None = None, extend_paid: bool = True) -> dict[str, Any]:
        """Registra (ou atualiza) a assinatura de uma licença emitida/renovada/reativada.

        ``lic``: license_id, type, customer (nome), customer_document, customer_ref, installation_id,
        hardware_id, expires_at, policy, site."""
        if lic.get("type") == "demo":
            raise CommercialError("Demonstração não tem assinatura.")
        pol = F.license_policy({"policy": lic.get("policy")}) if lic.get("policy") else F.license_policy({})
        now = iso(self.now())
        permanent = 1 if lic.get("type") == "permanent" else 0
        plan = plan_code or (lic.get("type") if lic.get("type") in dict((p[0], 1) for p in DEFAULT_PLANS) else "custom")
        with self.tx() as c:
            old = None
            if relink_from:
                old = c.execute("SELECT * FROM com_subscriptions WHERE license_id = ?", (relink_from,)).fetchone()
            cur = c.execute("SELECT * FROM com_subscriptions WHERE license_id = ?", (lic["license_id"],)).fetchone()
            if cur is None and old is None:
                if price_cents is None:
                    pr = c.execute("SELECT price_cents FROM com_plans WHERE code = ?", (plan,)).fetchone()
                    price_cents = int(pr["price_cents"]) if pr else 0
                c.execute(
                    """INSERT INTO com_subscriptions(license_id, customer_ref, customer_name, customer_document,
                           installation_id, hardware_id, site, plan_code, price_cents, validation, permanent, paid_until,
                           warn_days, grace_days, auto_suspend, contract_allows_suspension, operational_notes,
                           created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (lic["license_id"], str(lic.get("customer_ref") or ""), lic.get("customer") or "—",
                     lic.get("customer_document"), lic["installation_id"], lic["hardware_id"], lic.get("site"), plan,
                     int(price_cents or 0), pol["validation"], permanent, None if permanent else lic.get("expires_at"),
                     pol["warn_days"], pol["grace_days"],
                     1 if (auto_suspend if auto_suspend is not None else self.setting_int("auto_suspend")) else 0,
                     0 if contract_allows_suspension is False else 1, operational_notes, now, now))
                sid = c.execute("SELECT id FROM com_subscriptions WHERE license_id = ?", (lic["license_id"],)).fetchone()[0]
                self._history(c, sid, "create", None, self._state_of(c, sid), actor, self.host, None,
                              {"plan": plan, "validation": pol["validation"], "paid_until": lic.get("expires_at")})
                self.audit(actor, "create", lic["license_id"], {"plan": plan, "price_cents": price_cents}, c)
            else:
                base = dict(cur if cur is not None else old)
                sid = base["id"]
                before = evaluate(self.snapshot(base), self.now()).state.value
                new_paid = base["paid_until"]
                if extend_paid and lic.get("expires_at") and not permanent:
                    cand = parse(lic["expires_at"])
                    if new_paid is None or cand > parse(new_paid):
                        new_paid = iso(cand)
                c.execute(
                    """UPDATE com_subscriptions SET license_id = ?, installation_id = ?, hardware_id = ?,
                           customer_name = ?, customer_document = COALESCE(?, customer_document), site = COALESCE(?, site),
                           plan_code = ?, price_cents = COALESCE(?, price_cents), validation = ?, permanent = ?,
                           paid_until = ?, warn_days = ?, grace_days = ?, updated_at = ?, active = 1 WHERE id = ?""",
                    (lic["license_id"], lic["installation_id"], lic["hardware_id"], lic.get("customer") or base["customer_name"],
                     lic.get("customer_document"), lic.get("site"), plan if plan_code or lic.get("type") != "custom"
                     else base["plan_code"], price_cents, pol["validation"], permanent, None if permanent else new_paid,
                     pol["warn_days"], pol["grace_days"], now, sid))
                after_row = dict(c.execute("SELECT * FROM com_subscriptions WHERE id = ?", (sid,)).fetchone())
                after = evaluate(self.snapshot(after_row), self.now())
                if before in ("suspended", "expired", "suspension_scheduled") and not after.restricts \
                        and new_paid != base["paid_until"]:
                    c.execute("UPDATE com_subscriptions SET suspend_at = NULL, suspended_at = NULL, reactivated_at = ? "
                              "WHERE id = ?", (now, sid))
                self._history(c, sid, "relink" if base["license_id"] != lic["license_id"] else "edit", before,
                              self._state_of(c, sid), actor, self.host, None,
                              {"from": base["license_id"], "to": lic["license_id"], "paid_until": new_paid})
                self.audit(actor, "relink", lic["license_id"], {"from": base["license_id"]}, c)
        return self.subscription(int(sid))

    def edit(self, actor: Actor, sid: int, **fields: Any) -> dict:
        self._require(actor, "subscription_edit")
        allowed = {"plan_code", "price_cents", "customer_document", "contract_allows_suspension", "auto_suspend",
                   "operational_notes", "billing_provider", "maintenance_until", "active"}
        bad = set(fields) - allowed
        if bad:
            raise CommercialError("Campos não editáveis: " + ", ".join(sorted(bad)))
        if "plan_code" in fields and not self.conn().execute("SELECT 1 FROM com_plans WHERE code = ?",
                                                              (fields["plan_code"],)).fetchone():
            raise CommercialError("Plano desconhecido.")
        sub = self.subscription(sid)
        with self.tx() as c:
            for k, v in fields.items():
                if k in ("contract_allows_suspension", "auto_suspend", "active"):
                    v = 1 if v else 0
                c.execute(f"UPDATE com_subscriptions SET {k} = ?, updated_at = ? WHERE id = ?", (v, iso(self.now()), sid))
            self._history(c, sid, "edit", sub["state"], self._state_of(c, sid), actor, self.host, None, fields)
            self.audit(actor, "edit", sub["license_id"], fields, c)
        return self.subscription(sid)

    # ------------------------------------------------------------------ histórico
    def _state_of(self, c, sid: int) -> str:
        r = dict(c.execute("SELECT * FROM com_subscriptions WHERE id = ?", (sid,)).fetchone())
        return evaluate(self.snapshot(r), self.now()).state.value

    def _history(self, c, sid: int, action: str, before: str | None, after: str | None, actor: Actor, source: str,
                 reason: str | None, details: dict | None = None) -> None:
        c.execute("""INSERT INTO com_history(subscription_id, at, action, from_state, to_state, actor, source, reason,
                         details) VALUES (?,?,?,?,?,?,?,?,?)""",
                  (sid, iso(self.now()), action, before, after, actor.username, source, reason,
                   json.dumps(details or {}, ensure_ascii=False, default=str)))
        if after:
            c.execute("UPDATE com_subscriptions SET last_state = ? WHERE id = ?", (after, sid))

    def history(self, sid: int) -> list[dict]:
        rows = [dict(r) for r in self.conn().execute(
            "SELECT * FROM com_history WHERE subscription_id = ? ORDER BY id DESC", (sid,))]
        for r in rows:
            r["action_label"] = ACTION_LABELS.get(r["action"], r["action"])
        return rows

    def notifications(self, sid: int) -> list[dict]:
        return [dict(r) for r in self.conn().execute(
            "SELECT * FROM com_notifications WHERE subscription_id = ? ORDER BY id DESC", (sid,))]

    def payments(self, sid: int) -> list[dict]:
        return [dict(r) for r in self.conn().execute(
            "SELECT * FROM com_payments WHERE subscription_id = ? ORDER BY id DESC", (sid,))]

    def charges(self, sid: int | None = None, *, open_only: bool = False) -> list[dict]:
        q, a = "SELECT * FROM com_charges WHERE 1=1", []
        if sid is not None:
            q += " AND subscription_id = ?"
            a.append(sid)
        if open_only:
            q += " AND status IN ('issued','overdue','manual_check')"
        return [dict(r) for r in self.conn().execute(q + " ORDER BY id DESC", a)]

    def authorizations(self, sid: int) -> list[dict]:
        return [dict(r) for r in self.conn().execute(
            "SELECT id, authorization_id, license_id, seq, issued_at, valid_until, state, source, channel, actor "
            "FROM com_authorizations WHERE subscription_id = ? ORDER BY id DESC", (sid,))]

    def suspensions(self, sid: int) -> list[dict]:
        return [h for h in self.history(sid) if h["action"] in ("schedule_suspension", "cancel_suspension", "suspend")
                or (h["action"] == "state" and h["to_state"] == "suspended")]

    def reactivations(self, sid: int) -> list[dict]:
        return [h for h in self.history(sid) if h["action"] == "reactivate"]

    def _notify(self, c, sid: int, ev: Evaluation) -> None:
        kind = {"due_soon": "due_warning", "overdue": "overdue", "suspension_scheduled": "suspension_scheduled",
                "suspended": "suspended", "expired": "expired", "reactivated": "reactivated"}.get(ev.state.value)
        if not kind:
            return
        ref = iso(ev.suspend_at if kind == "suspension_scheduled" else ev.since if kind in ("suspended", "expired")
                  else ev.due_at) or "-"
        c.execute("INSERT OR IGNORE INTO com_notifications(subscription_id, at, kind, ref, audience, message) "
                  "VALUES (?,?,?,?,?,?)", (sid, iso(self.now()), kind, ref, "clinic_admin", ev.admin_message))

    def evaluate_all(self) -> list[dict]:
        """Registra as mudanças de estado decorrentes do tempo (vencimento, carência, suspensão programada)
        e os avisos correspondentes. Chamado periodicamente pelo servidor e ao abrir o License Manager."""
        changes = []
        with self.tx() as c:
            for r in c.execute("SELECT * FROM com_subscriptions WHERE active = 1").fetchall():
                d = dict(r)
                ev = evaluate(self.snapshot(d), self.now())
                self._notify(c, d["id"], ev)
                if ev.state.value != d["last_state"]:
                    self._history(c, d["id"], "state", d["last_state"], ev.state.value, SYSTEM, "política",
                                  "suspensão automática prevista em contrato" if ev.automatic else None,
                                  {"due_at": iso(ev.due_at), "grace_until": iso(ev.grace_until)})
                    changes.append({"license_id": d["license_id"], "from": d["last_state"], "to": ev.state.value})
        return changes

    # ------------------------------------------------------------------ confirmações
    def _confirm(self, action: str, actor: Actor, confirmed_by: tuple[str, str] | None) -> str | None:
        needed = [x.strip() for x in self.settings().get("confirm_actions", "").split(",") if x.strip()]
        if action not in needed or actor.role == "admin":
            return None
        if not confirmed_by or not confirmed_by[0]:
            raise CommercialError("Esta ação exige a confirmação de um administrador comercial (usuário e senha).")
        user, pw = confirmed_by
        if user.strip().lower() == actor.username.lower():
            raise CommercialError("A confirmação deve ser feita por outro usuário (administrador comercial).")
        if self.verify_admin is None or not self.verify_admin(user, pw):
            raise CommercialError("Confirmação recusada: usuário não é administrador comercial ou senha incorreta.")
        return user

    # ------------------------------------------------------------------ pagamentos e cobranças
    def confirm_payment(self, actor: Actor, sid: int, *, reference: str, source: str, periods: int = 1,
                        amount_cents: int | None = None, paid_at: datetime | None = None,
                        new_paid_until: datetime | None = None, charge_id: int | None = None) -> dict:
        """Pagamento **confirmado** (baixa do banco consultada ou conferência do financeiro).

        Idempotente pela referência (número do documento, código da cobrança, ID da transação)."""
        self._require(actor, "payments")
        reference = (reference or "").strip()
        if not reference:
            raise CommercialError("Informe a referência do pagamento confirmado (documento bancário).")
        sub = self.subscription(sid)
        if sub["permanent"]:
            raise CommercialError("Licença permanente: não há mensalidade (registre manutenção à parte).")
        c0 = self.conn()
        dup = c0.execute("SELECT * FROM com_payments WHERE reference = ?", (reference,)).fetchone()
        if dup is not None:
            with self.tx() as c:
                self._history(c, sid, "payment_duplicate", sub["state"], sub["state"], actor, source, None,
                              {"reference": reference})
            return {"duplicate": True, "payment": dict(dup), "subscription": self.subscription(sid)}
        periods = max(1, int(periods))
        prev = parse(sub["paid_until"])
        if new_paid_until is None:
            months = sub["plan_months"]
            if not months:
                raise CommercialError("Plano sem período fixo: informe até quando o pagamento quita a assinatura.")
            base = prev or self.now()
            new_paid_until = F.add_months(base + timedelta(seconds=1), int(months) * periods)
        if prev and new_paid_until <= prev:
            raise CommercialError("O novo vencimento deve ser posterior ao atual.")
        before = sub["state"]
        now = iso(self.now())
        with self.tx() as c:
            c.execute("""INSERT INTO com_payments(subscription_id, reference, source, amount_cents, periods, paid_at,
                             confirmed_by, confirmed_at, prev_paid_until, new_paid_until, charge_id)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                      (sid, reference, source, amount_cents, periods, iso(paid_at or self.now()), actor.username, now,
                       sub["paid_until"], iso(new_paid_until), charge_id))
            c.execute("UPDATE com_subscriptions SET paid_until = ?, last_payment_at = ?, last_payment_cents = ?, "
                      "updated_at = ? WHERE id = ?", (iso(new_paid_until), iso(paid_at or self.now()), amount_cents,
                                                       now, sid))
            after = self._state_of(c, sid)
            reactivated = False
            if before in ("suspended", "expired", "suspension_scheduled", "overdue"):
                c.execute("UPDATE com_subscriptions SET suspend_at = NULL, suspended_at = NULL WHERE id = ?", (sid,))
                after = self._state_of(c, sid)
                if before in ("suspended", "expired") and after not in ("suspended", "expired"):
                    c.execute("UPDATE com_subscriptions SET reactivated_at = ? WHERE id = ?", (now, sid))
                    reactivated = True
                    after = self._state_of(c, sid)
            self._history(c, sid, "payment", before, after, actor, source, None,
                          {"reference": reference, "amount_cents": amount_cents, "periods": periods,
                           "paid_until": iso(new_paid_until)})
            if reactivated:
                self._history(c, sid, "reactivate", before, after, actor, source, "pagamento confirmado",
                              {"reference": reference})
            self.audit(actor, "payment", sub["license_id"], {"reference": reference, "source": source,
                                                             "amount_cents": amount_cents,
                                                             "paid_until": iso(new_paid_until)}, c)
        return {"duplicate": False, "reactivated": reactivated, "subscription": self.subscription(sid)}

    def register_payment_claim(self, actor: Actor, sid: int, note: str) -> None:
        """Comprovante enviado pelo cliente ou promessa de pagamento: só registro, não quita."""
        self._require(actor, "commercial_view")
        sub = self.subscription(sid)
        with self.tx() as c:
            self._history(c, sid, "payment_claim", sub["state"], sub["state"], actor, self.host, note,
                          {"effect": "nenhum — aguarda confirmação bancária"})
            self.audit(actor, "payment_claim", sub["license_id"], {"note": note}, c)

    def register_charge(self, actor: Actor, sid: int, *, provider: str, provider_ref: str, amount_cents: int,
                        due_date: str, periods: int = 1, our_number: str | None = None) -> dict:
        self._require(actor, "billing")
        sub = self.subscription(sid)
        with self.tx() as c:
            c.execute("""INSERT INTO com_charges(subscription_id, provider, provider_ref, our_number, amount_cents,
                             due_date, periods, status, issued_at, issued_by) VALUES (?,?,?,?,?,?,?,'issued',?,?)""",
                      (sid, provider, provider_ref, our_number, int(amount_cents), due_date, int(periods),
                       iso(self.now()), actor.username))
            self._history(c, sid, "charge", sub["state"], sub["state"], actor, provider, None,
                          {"provider_ref": provider_ref, "amount_cents": amount_cents, "due_date": due_date,
                           "effect": "boleto emitido não quita a assinatura"})
            self.audit(actor, "charge", sub["license_id"], {"provider": provider, "ref": provider_ref}, c)
        return dict(self.conn().execute("SELECT * FROM com_charges WHERE provider = ? AND provider_ref = ?",
                                        (provider, provider_ref)).fetchone())

    def charge_by_ref(self, provider: str, provider_ref: str) -> dict | None:
        r = self.conn().execute("SELECT * FROM com_charges WHERE provider = ? AND provider_ref = ?",
                                (provider, provider_ref)).fetchone()
        return dict(r) if r else None

    def update_charge(self, actor: Actor, charge_id: int, *, status: str, provider_status: str | None,
                      paid_cents: int | None = None, paid_at: datetime | None = None) -> dict:
        """Situação consultada no banco. Somente ``paid`` confirma o pagamento da assinatura."""
        ch = dict(self.conn().execute("SELECT * FROM com_charges WHERE id = ?", (charge_id,)).fetchone())
        result: dict = {"charge_id": charge_id, "status": status}
        with self.tx() as c:
            c.execute("UPDATE com_charges SET status = ?, provider_status = ?, checked_at = ?, paid_cents = "
                      "COALESCE(?, paid_cents), paid_at = COALESCE(?, paid_at) WHERE id = ?",
                      (status, provider_status, iso(self.now()), paid_cents, iso(paid_at) if paid_at else None,
                       charge_id))
            if status != ch["status"]:
                st = self._state_of(c, ch["subscription_id"])
                self._history(c, ch["subscription_id"], "charge_status", st, st, actor, ch["provider"], None,
                              {"provider_ref": ch["provider_ref"], "from": ch["status"], "to": status,
                               "provider_status": provider_status})
        if status == "paid" and ch["status"] != "paid":
            result["payment"] = self.confirm_payment(
                actor, ch["subscription_id"], reference=f"{ch['provider']}:{ch['provider_ref']}",
                source=ch["provider"], periods=ch["periods"], amount_cents=paid_cents or ch["amount_cents"],
                paid_at=paid_at, charge_id=charge_id)
        return result

    def record_event(self, provider: str, event_key: str, payload: str, result: str = "") -> bool:
        """Registra uma notificação recebida do banco. ``False`` = repetida (já processada)."""
        try:
            with self.tx() as c:
                c.execute("INSERT INTO com_payment_events(provider, event_key, received_at, payload, result) "
                          "VALUES (?,?,?,?,?)", (provider, event_key, iso(self.now()), payload[:20000], result))
            return True
        except sqlite3.IntegrityError:
            return False

    def set_event_result(self, provider: str, event_key: str, result: str) -> None:
        with self.tx() as c:
            c.execute("UPDATE com_payment_events SET result = ? WHERE provider = ? AND event_key = ?",
                      (result, provider, event_key))

    def forget_event(self, provider: str, event_key: str) -> None:
        """Falha ao consultar o banco: a mesma notificação poderá ser reprocessada quando reenviada."""
        with self.tx() as c:
            c.execute("DELETE FROM com_payment_events WHERE provider = ? AND event_key = ?", (provider, event_key))

    # ------------------------------------------------------------------ carência, suspensão e reativação
    def grant_grace(self, actor: Actor, sid: int, days: int, reason: str,
                    confirmed_by: tuple[str, str] | None = None) -> dict:
        roles = [x.strip() for x in self.settings().get("grace_roles", "").split(",") if x.strip()]
        if actor.role not in roles:
            raise CommercialError(f"O perfil {ROLES.get(actor.role, actor.role)} não pode conceder prorrogação de "
                                  "carência (Políticas comerciais → perfis autorizados).")
        if not (reason or "").strip():
            raise CommercialError("Informe o motivo da prorrogação.")
        days = int(days)
        mx = self.setting_int("max_grace_extension_days")
        if not 1 <= days <= mx:
            raise CommercialError(f"A prorrogação deve ser de 1 a {mx} dias.")
        conf = self._confirm("grace", actor, confirmed_by)
        sub = self.subscription(sid)
        if sub["permanent"]:
            raise CommercialError("Licença permanente não tem carência.")
        base = max(parse(sub["grace_until"]) or self.now(), self.now())
        until = base + timedelta(days=days)
        with self.tx() as c:
            c.execute("UPDATE com_subscriptions SET grace_extra_until = ?, suspend_at = CASE WHEN suspend_at IS NOT NULL "
                      "AND suspend_at < ? THEN NULL ELSE suspend_at END, updated_at = ? WHERE id = ?",
                      (iso(until), iso(until), iso(self.now()), sid))
            after = self._state_of(c, sid)
            self._history(c, sid, "grace", sub["state"], after, actor, self.host, reason,
                          {"days": days, "grace_until": iso(until), "confirmed_by": conf})
            self.audit(actor, "grace", sub["license_id"], {"days": days, "until": iso(until), "reason": reason,
                                                           "confirmed_by": conf}, c)
        return self.subscription(sid)

    def _suspension_checks(self, sub: dict, at: datetime, operational_ack: bool) -> None:
        if sub["permanent"]:
            raise CommercialError("Licença permanente não é suspensa por inadimplência de mensalidade ou de "
                                  "manutenção opcional.")
        if not sub["contract_allows_suspension"]:
            raise CommercialError("O contrato desta assinatura não prevê suspensão por inadimplência.")
        if not operational_ack:
            raise CommercialError("Confirme que a política contratual e os requisitos operacionais da clínica foram "
                                  "verificados antes de suspender.")
        ev: Evaluation = sub["evaluation"]
        if ev.due_at is None or self.now() < ev.due_at or ev.state.value not in ("overdue", "expired",
                                                                                 "suspension_scheduled"):
            raise CommercialError("Não há inadimplência confirmada: a assinatura está paga até "
                                  f"{local(ev.due_at)}.")
        g = ev.grace_until or ev.due_at
        if at < g:
            raise CommercialError(f"A suspensão só pode ocorrer após o fim da carência ({local(g)}).")
        warned = self.conn().execute(
            "SELECT COUNT(*) FROM com_notifications WHERE subscription_id = ? AND ((kind IN ('due_warning','overdue') "
            "AND ref = ?) OR (kind = 'expired' AND ref = ?)) AND at <= ?",
            (sub["id"], iso(ev.due_at), iso(ev.grace_until), iso(self.now()))).fetchone()[0]
        if not warned:
            raise CommercialError("Nenhum aviso de vencimento/atraso foi registrado para este vencimento. Os avisos "
                                  "precisam ser emitidos antes da suspensão.")

    def schedule_suspension(self, actor: Actor, sid: int, at: datetime, reason: str, *, operational_ack: bool,
                            confirmed_by: tuple[str, str] | None = None) -> dict:
        self._require(actor, "suspend")
        if not (reason or "").strip():
            raise CommercialError("Informe o motivo da suspensão.")
        sub = self.subscription(sid)
        at = at.astimezone(timezone.utc)
        self._suspension_checks(sub, max(at, self.now()), operational_ack)
        conf = self._confirm("schedule_suspension", actor, confirmed_by)
        with self.tx() as c:
            c.execute("UPDATE com_subscriptions SET suspend_at = ?, suspension_reason = ?, updated_at = ? WHERE id = ?",
                      (iso(at), reason, iso(self.now()), sid))
            after = self._state_of(c, sid)
            self._history(c, sid, "schedule_suspension", sub["state"], after, actor, self.host, reason,
                          {"suspend_at": iso(at), "confirmed_by": conf, "operational_ack": True})
            self.audit(actor, "schedule_suspension", sub["license_id"], {"at": iso(at), "reason": reason,
                                                                         "confirmed_by": conf}, c)
            r = dict(c.execute("SELECT * FROM com_subscriptions WHERE id = ?", (sid,)).fetchone())
            self._notify(c, sid, evaluate(self.snapshot(r), self.now()))
        return self.subscription(sid)

    def cancel_suspension(self, actor: Actor, sid: int, reason: str) -> dict:
        self._require(actor, "suspend")
        sub = self.subscription(sid)
        if not sub["suspend_at"] and not sub["suspended_at"]:
            raise CommercialError("Não há suspensão programada ou aplicada.")
        if sub["state"] == "suspended":
            raise CommercialError("A suspensão já foi aplicada: use Reativar.")
        with self.tx() as c:
            c.execute("UPDATE com_subscriptions SET suspend_at = NULL, updated_at = ? WHERE id = ?",
                      (iso(self.now()), sid))
            self._history(c, sid, "cancel_suspension", sub["state"], self._state_of(c, sid), actor, self.host, reason)
            self.audit(actor, "cancel_suspension", sub["license_id"], {"reason": reason}, c)
        return self.subscription(sid)

    def suspend_now(self, actor: Actor, sid: int, reason: str, *, operational_ack: bool,
                    confirmed_by: tuple[str, str] | None = None) -> dict:
        self._require(actor, "suspend")
        if not (reason or "").strip():
            raise CommercialError("Informe o motivo da suspensão.")
        sub = self.subscription(sid)
        self._suspension_checks(sub, self.now(), operational_ack)
        conf = self._confirm("suspend", actor, confirmed_by)
        with self.tx() as c:
            c.execute("UPDATE com_subscriptions SET suspended_at = ?, suspension_reason = ?, updated_at = ? WHERE id = ?",
                      (iso(self.now()), reason, iso(self.now()), sid))
            after = self._state_of(c, sid)
            self._history(c, sid, "suspend", sub["state"], after, actor, self.host, reason,
                          {"confirmed_by": conf, "operational_ack": True})
            self.audit(actor, "suspend", sub["license_id"], {"reason": reason, "confirmed_by": conf}, c)
            r = dict(c.execute("SELECT * FROM com_subscriptions WHERE id = ?", (sid,)).fetchone())
            self._notify(c, sid, evaluate(self.snapshot(r), self.now()))
        return self.subscription(sid)

    def reactivate(self, actor: Actor, sid: int, reason: str, *, extend_until: datetime | None = None,
                   confirmed_by: tuple[str, str] | None = None) -> dict:
        """Reativação administrativa (acordo, erro de cobrança, decisão comercial).

        Remove a suspensão. Se o período pago já terminou, informe ``extend_until`` (prorrogação até a
        regularização) — sem isso a assinatura continuaria EXPIRADA."""
        self._require(actor, "reactivate")
        if not (reason or "").strip():
            raise CommercialError("Informe o motivo da reativação.")
        sub = self.subscription(sid)
        if sub["state"] not in ("suspended", "expired", "suspension_scheduled"):
            raise CommercialError("A assinatura não está suspensa nem expirada.")
        conf = self._confirm("reactivate", actor, confirmed_by)
        now = self.now()
        with self.tx() as c:
            c.execute("UPDATE com_subscriptions SET suspend_at = NULL, suspended_at = NULL, reactivated_at = ?, "
                      "grace_extra_until = CASE WHEN ? IS NOT NULL THEN ? ELSE grace_extra_until END, updated_at = ? "
                      "WHERE id = ?", (iso(now), iso(extend_until), iso(extend_until), iso(now), sid))
            after = self._state_of(c, sid)
            if CommercialState(after).restricts:
                raise CommercialError("O período pago e a carência já terminaram: informe até quando a assinatura "
                                      "fica liberada (prorrogação) ou confirme o pagamento.")
            self._history(c, sid, "reactivate", sub["state"], after, actor, self.host, reason,
                          {"extend_until": iso(extend_until), "confirmed_by": conf})
            self.audit(actor, "reactivate", sub["license_id"], {"reason": reason, "extend_until": iso(extend_until),
                                                                "confirmed_by": conf}, c)
        return self.subscription(sid)

    # ------------------------------------------------------------------ autorizações
    def build_authorization(self, actor: Actor, sid: int, *, channel: str, nonce: str | None = None) -> dict:
        """Dados da autorização de uso (assinados pelo host com a chave correspondente)."""
        self._require(actor, "authorize")
        if channel not in ("online", "offline"):
            raise CommercialError("Canal inválido.")
        sub = self.subscription(sid)
        if not sub["active"]:
            raise CommercialError("Assinatura encerrada.")
        now = self.now()
        ev: Evaluation = sub["evaluation"]
        if channel == "online":
            valid = now + timedelta(days=self.setting_int("auth_ttl_days"))
        elif sub["permanent"]:
            valid = now + timedelta(days=3650)
        else:
            valid = max(grace_end(self.snapshot(sub)) or now, now)
        with self.tx() as c:
            cur = c.execute("SELECT auth_seq FROM com_subscriptions WHERE id = ?", (sid,)).fetchone()[0]
            seq = max(int(cur) + 1, int(now.timestamp()))
            c.execute("UPDATE com_subscriptions SET auth_seq = ? WHERE id = ?", (seq, sid))
        commercial = self.snapshot(sub)
        commercial["state"] = ev.state.value
        return {
            "v": F.VERSION, "product_id": F.PRODUCT_ID, "kind": "authorization",
            "authorization_id": f"VYXA-{now:%Y%m%d}-{secrets.token_hex(6).upper()}",
            "license_id": sub["license_id"], "installation_id": sub["installation_id"],
            "hardware_id": sub["hardware_id"], "seq": seq, "issued_at": iso(now), "valid_until": iso(valid),
            "nonce": nonce, "source": "server" if self.host == "server" else "manager", "channel": channel,
            "issued_by": actor.username, "commercial": commercial,
            "online_tolerance_days": self.setting_int("online_tolerance_days"),
        }

    def record_authorization(self, actor: Actor, payload: dict, document: str) -> None:
        sub = self.subscription(payload["license_id"])
        with self.tx() as c:
            c.execute("""INSERT INTO com_authorizations(authorization_id, subscription_id, license_id, seq, issued_at,
                             valid_until, state, source, channel, actor, document) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                      (payload["authorization_id"], sub["id"], payload["license_id"], payload["seq"],
                       payload["issued_at"], payload["valid_until"], payload["commercial"]["state"], payload["source"],
                       payload["channel"], actor.username, document))
            if payload["channel"] == "offline":
                self._history(c, sub["id"], "authorization", sub["state"], sub["state"], actor, self.host, None,
                              {"authorization_id": payload["authorization_id"], "channel": "offline",
                               "valid_until": payload["valid_until"]})
                self.audit(actor, "authorization", sub["license_id"], {"authorization_id": payload["authorization_id"],
                                                                       "channel": payload["channel"]}, c)

    def record_contact(self, sid: int, version: str | None) -> None:
        with self.tx() as c:
            c.execute("UPDATE com_subscriptions SET last_contact_at = ?, last_contact_version = ? WHERE id = ?",
                      (iso(self.now()), (version or "")[:40], sid))

    # ------------------------------------------------------------------ painel
    def summary(self) -> dict[str, int]:
        out = {s.value: 0 for s in CommercialState}
        for s in self.subscriptions():
            out[s["state"]] += 1
        out["total"] = sum(out.values())
        return out


def money(cents: int | None) -> str:
    if cents is None:
        return "—"
    v = f"{int(cents) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {v}"


__all__ = ["CommercialEngine", "CommercialError", "Actor", "ROLES", "PERMS", "SYSTEM", "money", "ACTION_LABELS"]


def public(row: dict) -> dict:
    """Assinatura em formato JSON (API do License Server e interface remota)."""
    d = {k: v for k, v in row.items() if k != "evaluation"}
    ev = row.get("evaluation")
    d["evaluation"] = ev.as_dict() if ev is not None else None
    return d


ACTIONS = ("payment", "claim", "grace", "schedule-suspension", "cancel-suspension", "suspend", "reactivate", "edit")


def run_action(engine: CommercialEngine, actor: Actor, sid: int, name: str, data: dict, *,
               source: str = "manual") -> dict:
    """Ações da Gestão Comercial com dados JSON (mesma interface no License Manager e no servidor)."""
    conf = data.get("confirmed_by")
    conf_t = (str(conf.get("username") or ""), str(conf.get("password") or "")) if isinstance(conf, dict) else None

    def when(key: str) -> datetime | None:
        v = data.get(key)
        if not v:
            return None
        if isinstance(v, datetime):
            return v
        try:
            return F.parse_time(str(v))
        except ValueError as exc:
            raise CommercialError(f"Data inválida ({key}).") from exc

    if name == "payment":
        r = engine.confirm_payment(actor, sid, reference=str(data.get("reference") or ""), source=source,
                                   periods=int(data.get("periods") or 1),
                                   amount_cents=int(data["amount_cents"]) if data.get("amount_cents") not in (None, "")
                                   else None, paid_at=when("paid_at"), new_paid_until=when("new_paid_until"))
        r["subscription"] = public(r["subscription"])
        return r
    if name == "claim":
        engine.register_payment_claim(actor, sid, str(data.get("note") or ""))
        return {"ok": True}
    if name == "grace":
        return public(engine.grant_grace(actor, sid, int(data.get("days") or 0), str(data.get("reason") or ""), conf_t))
    if name == "schedule-suspension":
        at = when("at")
        if at is None:
            raise CommercialError("Informe a data da suspensão.")
        return public(engine.schedule_suspension(actor, sid, at, str(data.get("reason") or ""),
                                                 operational_ack=bool(data.get("operational_ack")), confirmed_by=conf_t))
    if name == "cancel-suspension":
        return public(engine.cancel_suspension(actor, sid, str(data.get("reason") or "")))
    if name == "suspend":
        return public(engine.suspend_now(actor, sid, str(data.get("reason") or ""),
                                         operational_ack=bool(data.get("operational_ack")), confirmed_by=conf_t))
    if name == "reactivate":
        return public(engine.reactivate(actor, sid, str(data.get("reason") or ""), extend_until=when("extend_until"),
                                        confirmed_by=conf_t))
    if name == "edit":
        return public(engine.edit(actor, sid, **(data.get("fields") or {})))
    raise CommercialError("Ação desconhecida.")


def detail(engine: CommercialEngine, sid: int) -> dict:
    return {"subscription": public(engine.subscription(sid)), "history": engine.history(sid),
            "notifications": engine.notifications(sid), "payments": engine.payments(sid),
            "charges": engine.charges(sid), "authorizations": engine.authorizations(sid),
            "suspensions": engine.suspensions(sid), "reactivations": engine.reactivations(sid)}
