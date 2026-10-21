"""Licenciamento offline do VYONIX DICOM Print (formato 2) — somente **verificação**.

Camadas de proteção contra cópia (defesa em camadas; nenhuma é absoluta isoladamente):

1. **Hardware** — componentes do VYONIX Hardware ID comparados com os autorizados (``hardware.py``).
2. **Instalação** — o VYONIX Installation ID precisa ser o da licença (``installation.py``).
3. **Assinatura** — Ed25519 com chave pública embutida (``keys.py``); qualquer alteração invalida.
4. **TPM** — se a licença inclui a chave do TPM, o TPM precisa assinar um desafio novo (``tpm.py``).
5. **Integridade de estado** — cofre selado em vários locais (``vault.py``) e VYONIX Time
   Integrity (``time_integrity.py``).

Política (versões comerciais): sem licença válida nem demonstração ativa, as funções licenciadas
(recepção C-STORE, impressão, Print SCP e regras) ficam **suspensas**; configurações, cadastros e
trabalhos na fila são preservados. Nas versões de desenvolvimento (``.devN``) a situação é
verificada e exibida, mas nada é suspenso.

Este módulo não contém nenhuma função de emissão: licenças, revalidações e listas de revogação são
assinadas somente pelo VYONIX License Manager.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from vyonix_protocol import formats as F
from vyonix_protocol.codec import b64e, canonical
from vyonix_protocol.crypto import verify_ed25519

from app import __version__, brand
from app.core.contracts import LicenseState, LicenseStatus
from app.core.errors import ValidationError
from app.database.connection import Database
from app.database.repositories.events_repo import Category, EventRepository
from app.licensing import tpm as tpm_mod
from app.licensing.demo import DemoService, fmt_remaining
from app.licensing.hardware import HardwareProfile, HardwareProvider
from app.licensing.installation import InstallationManager
from app.licensing.keys import PUBLIC_KEYS
from app.licensing.time_integrity import TimeIntegrity, TimeStatus
from app.licensing.vault import Vault
from app.utils.timeutil import from_iso, to_iso, utc_now_iso

PRODUCT = F.PRODUCT_NAME
ALL_FEATURES = F.FEATURES
FEATURE_LABELS = F.FEATURE_LABELS
DEMO_MARK = "VYONIX DICOM Print — DEMONSTRAÇÃO"
CACHE_S = 60.0
TPM_PROOF_S = 600.0
WARN_EXPIRY = timedelta(days=15)
CRITICAL_RECORDS = ("installation", "time", "demo", "activations", "revocation")


@dataclass
class LicenseData:
    license_id: str
    product_id: str
    type: str
    edition: str
    customer: str
    hardware_id: str
    hw: dict[str, Any]
    installation_id: str
    features: list[str]
    issued_at: str
    starts_at: str | None = None
    expires_at: str | None = None
    duration_hours: int | None = None
    max_devices: int | None = None
    max_printers: int | None = None
    reissue_of: str | None = None
    key_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def licensee(self) -> str:
        return self.customer

    @property
    def type_label(self) -> str:
        return F.LICENSE_TYPES.get(self.type, (self.type,))[0]

    @classmethod
    def from_payload(cls, p: dict, key_id: str = "") -> "LicenseData":
        cust = p.get("customer")
        name = cust.get("name") if isinstance(cust, dict) else str(cust or "")
        known = {f for f in cls.__dataclass_fields__ if f not in ("extra", "customer", "key_id")}
        return cls(customer=name, key_id=key_id, **{k: p.get(k) for k in known},
                   extra={k: v for k, v in p.items() if k not in known and k != "customer"})


@dataclass
class Verdict:
    status: LicenseStatus
    lic: LicenseData | None
    detail: dict[str, Any] = field(default_factory=dict)


class LicenseService:
    def __init__(self, db: Database, events: EventRepository, settings_get: Callable[[str], Any], *,
                 vault: Vault, hardware: HardwareProvider, tpm, installation: InstallationManager,
                 time_integrity: TimeIntegrity, demo: DemoService, public_keys: dict[str, str] | None = None,
                 enforced: bool | None = None, settings_set: Callable[[str, Any], None] | None = None) -> None:
        self.db = db
        self.events = events
        self.get = settings_get
        self.vault = vault
        self.hardware = hardware
        self.tpm = tpm
        self.installation = installation
        self.time = time_integrity
        self.demo = demo
        self.public_keys = PUBLIC_KEYS if public_keys is None else public_keys
        self.enforced = enforced_default() if enforced is None else enforced
        self.settings_set = settings_set
        self._lock = threading.Lock()
        self._cache: tuple[float, Verdict, str] | None = None
        self._tpm_proof: tuple[float, str, bool, str] | None = None
        self._last_state: str | None = None

    # ------------------------------------------------------------------ identificadores
    def installation_id(self) -> str:
        inst = self.installation.current().installation_id
        if self.settings_set and self.get("system.installation_id") != inst:
            try:
                self.settings_set("system.installation_id", inst)
            except Exception:  # noqa: BLE001 - exibição apenas
                pass
        return inst

    def profile(self, refresh: bool = False) -> HardwareProfile:
        return self.hardware.profile(refresh)

    def hardware_id(self) -> str:
        return self.profile().hardware_id

    # ------------------------------------------------------------------ solicitação
    def request_data(self, *, reason: str = "new", previous_license_id: str | None = None) -> dict[str, Any]:
        prof = self.profile(refresh=True)
        ts = self.time.check()
        demo = self.demo.state(ts.effective)
        current = self._active_row()
        data: dict[str, Any] = {
            "v": F.VERSION, "product_id": F.PRODUCT_ID, "product": F.PRODUCT_NAME,
            "request_id": secrets.token_hex(12), "hardware_id": prof.hardware_id, "hw": prof.digests,
            "installation_id": self.installation_id(), "app_version": __version__,
            "site": self.get("site.name") or None, "requested_at": to_iso(ts.wall),
            "reason": reason if reason in F.REACTIVATION_REASONS or reason == "new" else "other",
            "previous_license_id": previous_license_id or (current["license_id"] if current else None),
            "demo_used": demo.state != "available", "os": platform.platform(terse=True),
        }
        if prof.tpm:
            data["tpm"] = {"alg": prof.tpm["alg"], "pub": b64e(prof.tpm["pub"])}
            try:
                data["tpm"]["sig"] = b64e(self.tpm.sign(hashlib.sha256(F.request_signed_part(data)).digest()))
            except Exception as exc:  # noqa: BLE001
                data["tpm"]["error"] = str(exc)[:120]
        self.events.add(level="INFO", category=Category.LICENSE, action="license.request",
                        message="Solicitação de ativação gerada.", actor="system",
                        details={"request_id": data["request_id"], "hardware_id": prof.hardware_id,
                                 "installation_id": data["installation_id"], "reason": data["reason"]})
        return data

    def request_code(self, **kw) -> str:
        return F.encode_request(self.request_data(**kw))

    def request_file(self, **kw) -> str:
        return F.request_file(self.request_data(**kw))

    # ------------------------------------------------------------------ verificação
    def _verify_doc(self, text: str, fmt: str) -> F.SignedDoc:
        try:
            doc = F.parse_signed(text, fmt)
        except F.FormatError as exc:
            raise ValidationError(str(exc)) from exc
        key = self.public_keys.get(doc.key_id)
        if not key:
            raise ValidationError(f"Documento assinado por uma chave desconhecida ({doc.key_id or '—'}). Ele não foi "
                                  "emitido pelo VYONIX License Manager oficial.")
        if not verify_ed25519(key, doc.signed, doc.signature):
            raise ValidationError("Assinatura digital inválida: o documento foi alterado ou não é autêntico.")
        if doc.payload.get("product_id") != F.PRODUCT_ID:
            raise ValidationError(f"Documento de outro produto ({doc.payload.get('product_id')}).")
        return doc

    def _tpm_prove(self, prof: HardwareProfile) -> tuple[bool, str]:
        if not prof.tpm:
            return False, "TPM indisponível"
        digest = prof.digests.get("tpm") or ""
        now = time.monotonic()
        c = self._tpm_proof
        if c and c[1] == digest and now - c[0] < TPM_PROOF_S:
            return c[2], c[3]
        ok, msg = tpm_mod.prove(self.tpm, prof.tpm["alg"], prof.tpm["pub"])
        self._tpm_proof = (now, digest, ok, msg)
        return ok, msg

    def check(self, text: str, *, ts: TimeStatus | None = None, installing: bool = False) -> Verdict:
        """Valida um texto de licença sem gravar nada."""
        inst = self.installation_id()
        prof = self.profile()
        base = dict(installation_id=inst, hardware_id=prof.hardware_id)
        try:
            doc = self._verify_doc(text, F.LICENSE_FORMAT)
        except ValidationError as exc:
            return Verdict(LicenseStatus(LicenseState.INVALID, message=f"Licença recusada: {exc}", **base), None)
        errors = F.validate_license_payload(doc.payload)
        if errors:
            return Verdict(LicenseStatus(LicenseState.INVALID, message="Licença recusada: " + "; ".join(errors) + ".",
                                         **base), None)
        lic = LicenseData.from_payload(doc.payload, doc.key_id)
        kind = "demo_signed" if lic.type == "demo" else "commercial"
        info = dict(edition=lic.edition, features=tuple(lic.features), kind=kind, license_id=lic.license_id,
                    license_type=lic.type, max_devices=lic.max_devices, max_printers=lic.max_printers, **base)
        if lic.installation_id != inst:
            return Verdict(LicenseStatus(LicenseState.INSTALLATION_MISMATCH, message=(
                "Licença emitida para outra instalação do VYONIX (o programa foi reinstalado ou copiado). "
                "Exporte uma nova solicitação e peça a reativação ao administrador."), **info), lic)
        match = F.compare_hardware(lic.hw, prof.digests)
        detail: dict[str, Any] = {"hardware": match.__dict__}
        if not match.ok:
            return Verdict(LicenseStatus(LicenseState.HARDWARE_MISMATCH, message=match.reason
                                         + " Exporte uma nova solicitação e peça a reativação ao administrador.",
                                         **info), lic, detail)
        if lic.hw.get("tpm"):
            ok, msg = self._tpm_prove(prof)
            detail["tpm"] = msg
            if not ok:
                return Verdict(LicenseStatus(LicenseState.HARDWARE_MISMATCH,
                                             message=f"Prova de posse do TPM falhou: {msg}.", **info), lic, detail)
        revoked = self._revoked()
        if lic.license_id in revoked:
            return Verdict(LicenseStatus(LicenseState.REVOKED, message="Licença revogada pelo administrador"
                                         + (f" ({revoked[lic.license_id]})." if revoked[lic.license_id] else "."),
                                         **info), lic, detail)
        issued = F.parse_time(lic.issued_at)
        ts = ts or self.time.check(floor=issued)
        detail["time"] = ts.__dict__
        if not ts.ok:
            return Verdict(LicenseStatus(LicenseState.SUSPENDED, message=ts.message, **info), lic, detail)
        now = ts.effective
        if lic.starts_at and now < F.parse_time(lic.starts_at) - timedelta(hours=26):
            return Verdict(LicenseStatus(LicenseState.INVALID, message=(
                f"Licença válida somente a partir de {F.parse_time(lic.starts_at).astimezone():%d/%m/%Y}."), **info),
                lic, detail)
        exp = F.parse_time(lic.expires_at) if lic.expires_at else None
        if lic.type == "demo":
            act = self._activation(lic.license_id) or (now if installing else None)
            if act is None:
                act = now
            dur_end = act + timedelta(hours=int(lic.duration_hours or F.DEMO_HOURS))
            exp = min(exp, dur_end) if exp else dur_end
        if exp is not None and now >= exp:
            state = LicenseState.DEMO_EXPIRED if lic.type == "demo" else LicenseState.EXPIRED
            return Verdict(LicenseStatus(state, expires_at=exp, message=(
                f"{'Demonstração encerrada' if lic.type == 'demo' else 'Licença vencida'} em "
                f"{exp.astimezone():%d/%m/%Y %H:%M}. Solicite a renovação ao administrador."), **info), lic, detail)
        remaining = (exp - now).total_seconds() if exp else None
        warn = None
        if exp is not None and exp - now <= (timedelta(hours=24) if lic.type == "demo" else WARN_EXPIRY):
            warn = f"Vence em {fmt_remaining(exp - now)} ({exp.astimezone():%d/%m/%Y %H:%M})."
        state = LicenseState.DEMO if lic.type == "demo" else LicenseState.VALID
        text_ = (f"{lic.type_label} — {lic.edition}, para {lic.customer}"
                 + (f", válida até {exp.astimezone():%d/%m/%Y %H:%M}" if exp else ", sem vencimento") + ".")
        return Verdict(LicenseStatus(state, expires_at=exp, message=text_, remaining_s=remaining, warning=warn, **info),
                       lic, detail)

    # ------------------------------------------------------------------ estado
    def _active_row(self):
        try:
            return self.db.connection().execute(
                "SELECT license_id, raw FROM licenses WHERE status = 'active' ORDER BY id DESC LIMIT 1").fetchone()
        except Exception:  # noqa: BLE001
            return None

    def _activation(self, license_id: str) -> datetime | None:
        rec = self.vault.best("activations", _merge_activations)[0] or {}
        v = (rec.get("items") or {}).get(license_id)
        return from_iso(v) if v else None

    def _revoked(self) -> dict[str, str]:
        rec = self.vault.best("revocation")[0] or {}
        return dict(rec.get("revoked") or {})

    def integrity_issues(self) -> list[str]:
        out = []
        for name in CRITICAL_RECORDS:
            rd = self.vault.read(name)
            if rd.tampered:
                out.append(f"{name}: cópia adulterada em {', '.join(rd.tampered)}")
        return out

    def status(self, *, refresh: bool = False) -> LicenseStatus:
        return self._verdict(refresh).status

    def verdict(self, refresh: bool = False) -> Verdict:
        return self._verdict(refresh)

    def _token(self) -> str:
        """Muda quando outro processo (interface × serviço) altera licença, DEMO ou cofre."""
        try:
            r = self.db.connection().execute(
                """SELECT (SELECT MAX(updated_at) FROM licensing_vault),
                          (SELECT COUNT(*) || '-' || IFNULL(MAX(id), 0) || '-' || IFNULL(SUM(status = 'active'), 0)
                           FROM licenses)""").fetchone()
            return f"{r[0]}|{r[1]}"
        except Exception:  # noqa: BLE001
            return ""

    def _verdict(self, refresh: bool = False) -> Verdict:
        token = self._token()
        with self._lock:
            if self._cache and not refresh and time.monotonic() - self._cache[0] < CACHE_S \
                    and self._cache[2] == token:
                return self._cache[1]
        v = self._compute()
        with self._lock:
            self._cache = (time.monotonic(), v, self._token())
        if v.status.state.value != self._last_state:
            if self._last_state is not None:
                self.events.add(level="WARNING" if not v.status.active else "INFO", category=Category.LICENSE,
                                action="license.state", message=f"{v.status.state.label}: {v.status.message}",
                                actor="system", details={"state": v.status.state.value})
            self._last_state = v.status.state.value
        return v

    def _compute(self) -> Verdict:
        inst = self.installation_id()
        prof = self.profile()
        integrity = self.integrity_issues()
        row = self._active_row()
        floor = None
        if row is not None:
            try:
                floor = F.parse_time(F.parse_signed(row["raw"], F.LICENSE_FORMAT).payload["issued_at"])
            except Exception:  # noqa: BLE001
                floor = None
        ts = self.time.check(floor=floor)
        base = dict(installation_id=inst, hardware_id=prof.hardware_id)
        if integrity:
            return Verdict(LicenseStatus(LicenseState.SUSPENDED, message=(
                "Registros de ativação alterados fora do VYONIX (" + "; ".join(integrity) + "). Exporte o "
                "diagnóstico e solicite revalidação administrativa."), **base), None, {"integrity": integrity})
        lic_verdict = self.check(row["raw"], ts=ts) if row is not None else None
        if lic_verdict and lic_verdict.status.active:
            return lic_verdict
        if not ts.ok:
            return Verdict(LicenseStatus(LicenseState.SUSPENDED, message=ts.message, **base), None, {"time": ts.__dict__})
        demo = self.demo.state(ts.effective)
        if demo.state == "active":
            note = f" (licença instalada: {lic_verdict.status.message})" if lic_verdict else ""
            return Verdict(LicenseStatus(
                LicenseState.DEMO, kind="demo_local", features=tuple(F.FEATURES), edition="Demonstração",
                expires_at=demo.expires_at, remaining_s=demo.remaining.total_seconds(), message=demo.message + note,
                warning=(f"A demonstração termina em {fmt_remaining(demo.remaining)}." if demo.warning else None),
                **base), None, {"demo": demo.__dict__})
        if lic_verdict:
            return lic_verdict
        if demo.state == "expired":
            return Verdict(LicenseStatus(LicenseState.DEMO_EXPIRED, kind="demo_local", expires_at=demo.expires_at,
                                         message=demo.message, **base), None, {"demo": demo.__dict__})
        msg = "Nenhuma licença instalada."
        if demo.state == "available":
            msg += " Inicie a demonstração de 5 dias ou ative a licença comercial."
        elif demo.state == "inconsistent":
            msg += " " + demo.message
        return Verdict(LicenseStatus(LicenseState.NOT_ACTIVATED, message=msg, **base), None, {"demo": demo.__dict__})

    def license_data(self) -> LicenseData | None:
        return self._verdict().lic

    def time_status(self) -> TimeStatus:
        return self.time.check()

    # ------------------------------------------------------------------ política
    def active(self) -> bool:
        return self.status().active

    def allows(self, feature: str) -> bool:
        if not self.enforced:
            return True
        st = self.status()
        return st.active and feature in st.features

    def suspension_reason(self) -> str | None:
        if not self.enforced:
            return None
        st = self.status()
        return None if st.active else f"{st.state.label}: {st.message}"

    def evaluation_mode(self) -> bool:
        """Marca nas impressões: demonstração."""
        st = self.status()
        return st.state == LicenseState.DEMO

    def mark_text(self) -> str | None:
        return DEMO_MARK if self.evaluation_mode() else None

    def device_limit(self) -> int | None:
        if not self.enforced:
            return None
        st = self.status()
        return st.max_devices if st.state == LicenseState.VALID else None

    def printer_limit(self) -> int | None:
        if not self.enforced:
            return None
        st = self.status()
        return st.max_printers if st.state == LicenseState.VALID else None

    def printer_allowed(self, printer: str, *, actor: str = "system") -> tuple[bool, str]:
        """Vagas de impressora da licença: a primeira impressão em cada impressora ocupa uma vaga."""
        from app.printing.service import is_pdf
        limit = self.printer_limit()
        st = self.status()
        if limit is None or is_pdf(printer) or not st.license_id:
            return True, ""
        conn = self.db.connection()
        used = [r["printer"] for r in conn.execute(
            "SELECT printer FROM license_printers WHERE license_id = ? ORDER BY id", (st.license_id,))]
        if printer in used:
            return True, ""
        if len(used) >= limit:
            return False, (f"A licença autoriza {limit} impressora(s), já ocupada(s) por: {', '.join(used)}. "
                           "Libere uma vaga na página Licença (administrador) ou solicite a ampliação.")
        conn.execute("INSERT OR IGNORE INTO license_printers(license_id, printer, added_at, added_by) VALUES (?,?,?,?)",
                     (st.license_id, printer, utc_now_iso(), actor))
        self.events.add(level="INFO", category=Category.LICENSE, action="license.printer",
                        message=f"Impressora “{printer}” ocupou a vaga {len(used) + 1} de {limit} da licença.",
                        actor=actor)
        return True, ""

    def licensed_printers(self) -> list[dict[str, Any]]:
        st = self.status()
        if not st.license_id:
            return []
        return [dict(r) for r in self.db.connection().execute(
            "SELECT printer, added_at, added_by FROM license_printers WHERE license_id = ? ORDER BY id",
            (st.license_id,))]

    def release_printer(self, printer: str, *, actor: str) -> None:
        st = self.status()
        self.db.connection().execute("DELETE FROM license_printers WHERE license_id = ? AND printer = ?",
                                     (st.license_id, printer))
        self.events.add(level="WARNING", category=Category.LICENSE, action="license.printer_release",
                        message=f"Vaga da impressora “{printer}” liberada.", actor=actor)

    def policy_text(self) -> str:
        if not self.enforced:
            return ("Versão de desenvolvimento/homologação: a licença é verificada e exibida, mas nenhuma função "
                    "é suspensa.")
        st = self.status()
        if st.state == LicenseState.DEMO:
            return ("Demonstração: todos os recursos funcionam; as páginas impressas identificam a demonstração. "
                    "As configurações são preservadas na ativação comercial.")
        if st.active:
            return "Recursos limitados ao que a licença autoriza."
        return ("Funções licenciadas suspensas (recepção DICOM, impressão, Print SCP e regras). Cadastros, "
                "configurações e trabalhos na fila são preservados e voltam a funcionar após a ativação.")

    def _invalidate(self) -> None:
        with self._lock:
            self._cache = None

    # ------------------------------------------------------------------ ações do cliente
    def start_demo(self, *, actor: str) -> LicenseStatus:
        ts = self.time.check()
        if not ts.ok:
            raise ValidationError(ts.message)
        if self.integrity_issues():
            raise ValidationError("Registros de ativação inconsistentes: a demonstração não pode ser iniciada. "
                                  "Exporte o diagnóstico e contate o administrador.")
        prof = self.profile(refresh=True)
        before = self.demo.state(ts.effective)
        if before.state != "available":
            raise ValidationError({"active": "A demonstração já está em andamento.",
                                   "expired": "A demonstração deste computador já foi utilizada. "
                                              "Ative a licença comercial ou solicite uma DEMO assinada.",
                                   "inconsistent": before.message}.get(before.state, before.message))
        st = self.demo.start(ts.effective, hardware_id=prof.hardware_id, hw=prof.digests,
                             installation_id=self.installation_id())
        self.events.add(level="INFO", category=Category.LICENSE, action="license.demo_start",
                        message=f"Demonstração de 5 dias iniciada (até {st.expires_at.astimezone():%d/%m/%Y %H:%M}).",
                        actor=actor, details={"hardware_id": prof.hardware_id})
        self._invalidate()
        return self.status(refresh=True)

    def install(self, text: str, *, actor: str) -> LicenseStatus:
        v = self.check(text, installing=True)
        st, lic = v.status, v.lic
        if not st.active or lic is None:
            self.events.add(level="WARNING", category=Category.LICENSE, action="license.rejected",
                            message=f"Licença recusada: {st.message}", actor=actor)
            raise ValidationError(st.message)
        conn = self.db.connection()
        now = utc_now_iso()
        ts = self.time.check()
        if self._activation(lic.license_id) is None:
            rec = self.vault.best("activations", _merge_activations)[0] or {"items": {}}
            items = dict(rec.get("items") or {})
            items[lic.license_id] = to_iso(ts.effective)
            self.vault.write("activations", {"items": items, "seq": rec.get("seq", 0)})
        signature = json.loads(text)["signature"]
        with self.db.transaction():
            conn.execute("UPDATE licenses SET status = 'superseded' WHERE status = 'active'")
            conn.execute(
                """INSERT INTO licenses(license_id, edition, license_type, features_json, licensee, installation_id,
                       hardware_id, issued_at, expires_at, signature, raw, status, installed_at, activated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                   ON CONFLICT(license_id) DO UPDATE SET status = 'active', raw = excluded.raw,
                       installed_at = excluded.installed_at""",
                (lic.license_id, lic.edition, lic.type, json.dumps(lic.features), lic.customer, lic.installation_id,
                 lic.hardware_id, lic.issued_at, lic.expires_at, signature, text, now, now))
            self.events.add(level="INFO", category=Category.LICENSE, action="license.install",
                            message=f"Licença {lic.type_label} instalada ({lic.customer}, {lic.license_id}).",
                            actor=actor, details={"license_id": lic.license_id, "features": lic.features,
                                                  "hardware_id": lic.hardware_id, "reissue_of": lic.reissue_of})
        self._invalidate()
        return self.status(refresh=True)

    def remove(self, *, actor: str) -> None:
        with self.db.transaction():
            self.db.connection().execute("UPDATE licenses SET status = 'superseded' WHERE status = 'active'")
            self.events.add(level="WARNING", category=Category.LICENSE, action="license.remove",
                            message="Licença removida desta instalação.", actor=actor)
        self._invalidate()

    def end_activation(self, reason: str, *, actor: str = "installer") -> int:
        """Desinstalação: encerra a ativação local (as licenças desta instalação deixam de valer)."""
        conn = self.db.connection()
        with self.db.transaction():
            n = conn.execute("UPDATE licenses SET status = 'ended', ended_at = ?, ended_reason = ? "
                             "WHERE status = 'active'", (utc_now_iso(), reason)).rowcount
            self.events.add(level="WARNING", category=Category.LICENSE, action="license.ended",
                            message=f"Ativação local encerrada ({reason}).", actor=actor)
        self._invalidate()
        return n

    def history(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.connection().execute(
            """SELECT license_id, edition, license_type, licensee, issued_at, expires_at, status, installed_at,
                      ended_reason FROM licenses ORDER BY id DESC""")]

    # ------------------------------------------------------------------ diagnóstico e revalidação
    def diagnostic(self) -> dict[str, Any]:
        v = self._verdict(refresh=True)
        prof = self.profile()
        ts = self.time.check()
        nonce = secrets.token_hex(12)
        pend = self.vault.best("revalidation")[0] or {}
        pending = dict(pend.get("pending") or {})
        pending[nonce] = to_iso(ts.wall)
        pending = dict(sorted(pending.items(), key=lambda kv: kv[1])[-10:])
        self.vault.write("revalidation", {**pend, "pending": pending})
        hist = [dict(r) for r in self.db.connection().execute(
            "SELECT at, kind, wall, trusted, delta_s, boot_id, process, detail FROM time_integrity_log "
            "ORDER BY id DESC LIMIT 200")]
        tstate = self.time.state() or {}
        data = {
            "format": F.DIAGNOSTIC_FORMAT, "v": F.VERSION, "product_id": F.PRODUCT_ID, "app_version": __version__,
            "generated_at": to_iso(ts.wall), "request_id": nonce,
            "hardware_id": prof.hardware_id, "hw": prof.digests,
            "components": dict(prof.summary()), "installation_id": self.installation_id(),
            "status": {"state": v.status.state.value, "message": v.status.message, "license_id": v.status.license_id},
            "time": {"wall": to_iso(ts.wall), "trusted": to_iso(ts.trusted), "effective": to_iso(ts.effective),
                     "issue": ts.issue, "message": ts.message, "first_seen": tstate.get("first_seen"),
                     "anomalies": tstate.get("anomalies", 0)},
            "time_history": hist, "integrity": self.integrity_issues(),
            "tpm": self.tpm.info() if self.tpm else {"available": False},
            "os": platform.platform(terse=True), "site": self.get("site.name") or None,
        }
        if isinstance(data["tpm"].get("pub"), bytes):
            data["tpm"]["pub"] = b64e(data["tpm"]["pub"])
        self.events.add(level="INFO", category=Category.LICENSE, action="license.diagnostic",
                        message="Diagnóstico de licenciamento exportado.", actor="system",
                        details={"request_id": nonce})
        return data

    def apply_revalidation(self, text: str, *, actor: str) -> str:
        doc = self._verify_doc(text, F.REVALIDATION_FORMAT)
        p = doc.payload
        prof = self.profile(refresh=True)
        if p.get("installation_id") != self.installation_id():
            raise ValidationError("Revalidação emitida para outra instalação.")
        if not F.compare_hardware(p.get("hw") or {}, prof.digests).ok:
            raise ValidationError("Revalidação emitida para outro computador.")
        pend = self.vault.best("revalidation")[0] or {}
        pending = dict(pend.get("pending") or {})
        used = list(pend.get("used") or [])
        rid = p.get("request_id")
        if rid in used:
            raise ValidationError("Esta revalidação já foi aplicada.")
        if rid not in pending:
            raise ValidationError("A revalidação não corresponde a um diagnóstico exportado por esta instalação.")
        trusted = F.parse_time(p["trusted_time"])
        actions = p.get("actions") or ["time"]
        done = []
        if "integrity" in actions:
            for name in CRITICAL_RECORDS:
                rd = self.vault.read(name)
                if rd.tampered:
                    valid = rd.valid
                    if name == "demo" and not valid:
                        self.demo.mark_used(trusted, "revalidation")
                    elif valid:
                        self.vault.write(name, max(valid, key=lambda r: int(r.get("seq", 0))))
                    else:
                        self.vault.delete(name)
            done.append("integridade dos registros")
        if "time" in actions or "integrity" in actions:
            self.time.revalidate(trusted, actor=f"{actor} / {p.get('issued_by', 'administrador')}")
            done.append("horário confiável")
        pending.pop(rid, None)
        used.append(rid)
        self.vault.write("revalidation", {**pend, "pending": pending, "used": used[-50:]})
        self.events.add(level="WARNING", category=Category.LICENSE, action="license.revalidated",
                        message="Revalidação administrativa aplicada: " + ", ".join(done) + ".", actor=actor,
                        details={"request_id": rid, "reason": p.get("reason")})
        self._invalidate()
        return "Revalidação aplicada: " + ", ".join(done) + "."

    def apply_revocation(self, text: str, *, actor: str) -> str:
        doc = self._verify_doc(text, F.REVOCATION_FORMAT)
        p = doc.payload
        cur = self.vault.best("revocation")[0] or {}
        seq = int(p.get("seq", 0))
        if seq <= int(cur.get("list_seq", 0)):
            raise ValidationError(f"Lista de revogação mais antiga que a instalada (nº {seq} ≤ {cur.get('list_seq', 0)}).")
        revoked = {str(x["license_id"]): str(x.get("reason") or "") for x in p.get("revoked") or []}
        self.vault.write("revocation", {**cur, "list_seq": seq, "issued_at": p.get("issued_at"), "revoked": revoked})
        self.events.add(level="WARNING", category=Category.LICENSE, action="license.revocation_list",
                        message=f"Lista de revogação nº {seq} instalada ({len(revoked)} licença(s)).", actor=actor)
        self._invalidate()
        st = self.status(refresh=True)
        return f"Lista nº {seq} instalada. Situação atual: {st.state.label}."


def _merge_activations(recs: list[dict[str, Any]]) -> dict[str, Any]:
    items: dict[str, str] = {}
    for r in recs:
        for k, v in (r.get("items") or {}).items():
            if k not in items or v < items[k]:
                items[k] = v
    best = max(recs, key=lambda r: int(r.get("seq", 0)))
    return {**best, "items": items}


def enforced_default() -> bool:
    flag = os.environ.get("VYONIX_LICENSE_ENFORCE")
    if flag is not None:
        return flag == "1"
    return ".dev" not in __version__


__all__ = ["LicenseService", "LicenseData", "Verdict", "PRODUCT", "ALL_FEATURES", "FEATURE_LABELS", "DEMO_MARK",
           "enforced_default", "brand", "canonical"]
