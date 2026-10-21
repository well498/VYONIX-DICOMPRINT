"""Assinatura comercial no VYONIX DICOM Print: autorizações de uso e estado comercial.

A **licença** identifica cliente, computador, instalação, recursos e a política comercial (assinada).
A **autorização de uso** (``vyonix-authorization``) traz a situação comercial atual — período pago,
carência, suspensão programada ou aplicada, reativação — e chega por dois caminhos:

* **online** — resposta do VYONIX License Server a uma consulta deste computador (com um número
  aleatório de uso único, que impede reaproveitar respostas antigas);
* **offline** — arquivo de renovação ``.vyauth`` emitido pelo VYONIX License Manager.

Proteções: assinatura Ed25519 de uma chave com escopo "authorization"; licença, instalação e
hardware conferidos; número de sequência sempre crescente (uma autorização antiga não substitui uma
mais nova); data de emissão conferida contra o horário confiável (Time Integrity).

Sem nenhuma autorização, a própria licença vale como a primeira: período pago até ``expires_at``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from vyonix_protocol import formats as F
from vyonix_commercial.states import Evaluation, evaluate, parse

from app.core.errors import ValidationError
from app.licensing.vault import Vault
from app.utils.timeutil import to_iso, utc_now_iso

CONNECTIVITY_LABELS = {
    "offline": "Licença offline (sem consulta ao servidor)",
    "pending": "Aguardando o primeiro contato com o License Server",
    "ok": "License Server: contato normal",
    "no_internet": "Internet ou DNS indisponível",
    "server_unavailable": "License Server indisponível",
    "rejected": "License Server recusou a consulta",
    "invalid_response": "Resposta inválida do servidor (suspeita de adulteração)",
}
FUTURE_SKEW = timedelta(hours=26)


@dataclass
class Commercial:
    evaluation: Evaluation
    policy: dict[str, Any]
    auth: dict[str, Any] | None
    connectivity: str | None
    connectivity_detail: str
    auth_expired_since: datetime | None = None      # validação online: fim da tolerância sem contato
    tolerance_until: datetime | None = None
    revoked: str | None = None


class AuthorizationBook:
    """Autorizações aplicadas (cofre selado + tabela de histórico)."""

    def __init__(self, vault: Vault, db) -> None:
        self.vault = vault
        self.db = db

    # ------------------------------------------------------------------ leitura
    def _rec(self) -> dict[str, Any]:
        return self.vault.best("authorization")[0] or {}

    def current(self, license_id: str) -> dict[str, Any] | None:
        item = (self._rec().get("items") or {}).get(license_id)
        return dict(item["payload"]) if item else None

    def online(self) -> dict[str, Any]:
        return self.vault.best("online")[0] or {}

    def set_online(self, **values: Any) -> dict[str, Any]:
        rec = {**self.online(), **values}
        self.vault.write("online", rec)
        return rec

    # ------------------------------------------------------------------ aplicação
    def apply(self, doc: F.SignedDoc, raw: str, *, lic, hardware_digests: dict, installation_id: str, now: datetime,
              actor: str, expected_nonce: str | None = None) -> dict[str, Any]:
        p = doc.payload
        errors = F.validate_authorization_payload(p)
        if errors:
            raise ValidationError("Autorização recusada: " + "; ".join(errors) + ".")
        if lic is None:
            raise ValidationError("Nenhuma licença comercial instalada para receber a autorização.")
        if p["license_id"] != lic.license_id:
            raise ValidationError(f"Autorização de outra licença ({p['license_id']}); a licença instalada é "
                                  f"{lic.license_id}.")
        if p["installation_id"] != installation_id:
            raise ValidationError("Autorização emitida para outra instalação do VYONIX.")
        if p["hardware_id"] != lic.hardware_id or not F.compare_hardware(lic.hw, hardware_digests).ok:
            raise ValidationError("Autorização emitida para outro computador.")
        if F.parse_time(p["issued_at"]) > now + FUTURE_SKEW:
            raise ValidationError("Autorização com data de emissão no futuro: confira data e hora do computador.")
        if p.get("channel") == "online":
            if expected_nonce is None:
                raise ValidationError("Autorizações online só são aceitas como resposta a uma consulta deste "
                                      "computador. Para renovação offline, use o arquivo emitido pelo License Manager.")
            if p.get("nonce") != expected_nonce:
                raise ValidationError("Resposta do servidor não corresponde a esta consulta (resposta repetida ou "
                                      "adulterada).")
        rec = self._rec()
        items = dict(rec.get("items") or {})
        cur = items.get(lic.license_id)
        used = list(rec.get("used") or [])
        if cur and int(p["seq"]) <= int(cur["payload"]["seq"]):
            if p["authorization_id"] == cur["payload"]["authorization_id"]:
                raise ValidationError("Esta autorização já foi aplicada.")
            raise ValidationError("Autorização mais antiga que a instalada (reutilização de autorização anterior "
                                  "recusada).")
        if p["authorization_id"] in used:
            raise ValidationError("Esta autorização já foi aplicada.")
        items[lic.license_id] = {"payload": p, "applied_at": to_iso(now)}
        used.append(p["authorization_id"])
        self.vault.write("authorization", {"items": items, "used": used[-200:], "seq": int(rec.get("seq", 0))})
        try:
            self.db.connection().execute(
                """INSERT OR IGNORE INTO license_authorizations(authorization_id, license_id, seq, source, channel,
                       issued_at, issued_by, valid_until, state, applied_at, applied_by, raw)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (p["authorization_id"], p["license_id"], int(p["seq"]), p["source"], p.get("channel") or "offline",
                 p["issued_at"], p.get("issued_by"), p["valid_until"], p["commercial"].get("state") or "",
                 utc_now_iso(), actor, raw))
        except Exception:  # noqa: BLE001 - o cofre é a referência; a tabela é histórico
            pass
        return p

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.connection().execute(
            "SELECT authorization_id, license_id, seq, source, channel, issued_at, issued_by, valid_until, state, "
            "applied_at, applied_by FROM license_authorizations ORDER BY id DESC LIMIT ?", (limit,))]

    # ------------------------------------------------------------------ avaliação
    def evaluate(self, lic, now: datetime) -> Commercial:
        payload_policy = lic.extra.get("policy") if lic.extra else None
        policy = F.license_policy({"policy": payload_policy} if payload_policy is not None else {})
        auth = self.current(lic.license_id)
        if auth:
            snap = dict(auth["commercial"])
        else:
            snap = {"permanent": lic.type == "permanent", "paid_until": lic.expires_at,
                    "warn_days": policy["warn_days"], "grace_days": policy["grace_days"]}
        ev = evaluate(snap, now)
        out = Commercial(ev, policy, auth, None, "", revoked=(auth or {}).get("revoked") or None)
        if policy["validation"] != "online":
            out.connectivity = "offline"
            return out
        on = self.online()
        out.connectivity = on.get("result") or "pending"
        tol = timedelta(days=int(auth.get("online_tolerance_days", policy["online_tolerance_days"]) if auth
                                 else policy["online_tolerance_days"]))
        if auth and auth.get("channel") == "online":
            base = F.parse_time(auth["valid_until"])
        else:
            base = F.parse_time(lic.issued_at)
        out.tolerance_until = base + tol
        last_ok = on.get("last_ok")
        if now > base:
            out.connectivity_detail = (
                f"Sem autorização online renovada desde {base.astimezone():%d/%m/%Y %H:%M}"
                + (f" (último contato: {parse(last_ok).astimezone():%d/%m/%Y %H:%M})" if last_ok else "")
                + f". Tolerância até {out.tolerance_until.astimezone():%d/%m/%Y %H:%M}.")
            if now >= out.tolerance_until:
                out.auth_expired_since = out.tolerance_until
        if on.get("message") and out.connectivity not in ("ok", "pending"):
            out.connectivity_detail = (on["message"] + " " + out.connectivity_detail).strip()
        return out


def history_add(db, *, license_id: str | None, kind: str, from_state: str | None, to_state: str, source: str,
                actor: str, detail: Any = None) -> None:
    try:
        db.connection().execute(
            "INSERT INTO license_state_history(at, license_id, kind, from_state, to_state, source, actor, detail) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (utc_now_iso(), license_id, kind, from_state, to_state, source, actor,
             detail if isinstance(detail, str) or detail is None else json.dumps(detail, ensure_ascii=False,
                                                                                    default=str)))
    except Exception:  # noqa: BLE001 - histórico não pode derrubar a verificação
        pass
