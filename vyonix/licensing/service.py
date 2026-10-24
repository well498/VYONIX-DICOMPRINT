"""Licenciamento modular do VYONIX Core (licença v3, compatível com a v2).

**Somente verificação.** Nenhuma função aqui emite licenças, autorizações ou demonstrações: tudo é
assinado pelo VYONIX License Manager (chave privada do fornecedor, fora das clínicas) ou, para
autorizações de uso online, pelo VYONIX License Server.

Identidade da instalação compartilhada com o VYONIX DICOM Print: o mesmo cofre selado
(``ProgramData\\VYONIX\\Licensing`` e registro do Windows), o mesmo Installation ID, o mesmo
VYONIX Hardware ID, o mesmo Time Integrity e a mesma lista de revogação. Uma licença v3 instalada no
Core vale também para o Print do mesmo servidor (o Print lê os campos legados) e vice-versa.

O que é conferido ao aplicar uma licença: assinatura Ed25519 com chave embutida e de escopo
"license", produto, Installation ID, componentes de hardware (e prova de posse do TPM, quando a
licença o inclui), revogação, data de emissão contra o horário confiável, e o mapa de módulos.

Direitos por módulo (``licensing.entitlements``):

* ``subscription`` / ``permanent`` — seguem o **contrato** da licença: período pago, carência,
  suspensão e reativação vêm das autorizações de uso (online ou arquivo ``.vyauth``), avaliadas pelo
  mesmo cálculo do License Server (``vyonix_commercial.states``).
* ``demo`` — conta a partir da primeira aplicação (registrada no cofre pelo ``grant_id``), por N
  dias. Prorrogação: nova licença com o mesmo ``grant_id`` e mais dias. Conversão: o módulo passa a
  seguir o contrato.

Limites: a contagem de usuários/unidades do Core é conferida antes de criar; os limites do PRINT
continuam aplicados pelo próprio DICOM Print.

Restrições honestas (documentadas): nenhuma proteção offline é absoluta — uma restauração completa
do disco (cofre, registro e banco juntos) a um estado anterior não pode ser detectada só pelo
computador; a validação online reduz esse risco. A suspensão comercial nunca apaga dados nem impede a
consulta dos dados clínicos já existentes.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vyonix import __version__
from vyonix.audit import service as audit
from vyonix.errors import Conflict, NotLicensed, ValidationFailed
from vyonix.events.bus import publish
from vyonix.licensing.models import Entitlement, LicenseDocument
from vyonix_protocol import formats as F
from vyonix_protocol.codec import b64e
from vyonix_protocol.crypto import verify_ed25519

# Componentes compartilhados com o VYONIX DICOM Print (somente verificação e identidade).
from app.core.errors import ValidationError as _PrintValidationError
from app.licensing import tpm as tpm_mod
from app.licensing.hardware import HardwareProvider
from app.licensing.installation import InstallationManager
from app.licensing.keys import KEY_SCOPES, PUBLIC_KEYS, key_policy_error
from app.licensing.subscription import CONNECTIVITY_LABELS, AuthorizationBook
from app.licensing.time_integrity import SystemClock, TimeIntegrity
from app.licensing.vault import FileBackend, RegistryBackend, Vault, machine_sealer

GRANTS_RECORD = "platform_grants"
UNLICENSED_CORE_LIMITS = {"users": 3, "sites": 1}
CACHE_S = 30.0
TPM_PROOF_S = 600.0


# --------------------------------------------------------------------------- identidade da máquina

@dataclass
class Machine:
    vault: Vault
    hardware: HardwareProvider
    tpm: Any
    installation: InstallationManager
    time: TimeIntegrity

    @classmethod
    def build(cls, state_dir: Path, *, isolated: bool = False) -> "Machine":
        """Componentes reais: cofre em ``state_dir`` (+ registro do Windows), TPM, relógio do sistema."""
        backends: list = [FileBackend(state_dir)]
        if sys.platform == "win32" and not isolated:
            backends.append(RegistryBackend())
        vault = Vault(backends, machine_sealer(state_dir, use_registry=not isolated and sys.platform == "win32"))
        tpm = tpm_mod.NullTpm("pasta isolada") if isolated else tpm_mod.default_tpm()
        return cls(vault=vault, hardware=HardwareProvider(tpm), tpm=tpm, installation=InstallationManager(vault),
                   time=TimeIntegrity(vault, SystemClock(), process="core"))


class _NoSqliteHistory:
    """O ``AuthorizationBook`` do Print grava um histórico no SQLite dele; no Core o histórico fica em
    ``licensing.license_documents`` e na auditoria. A gravação no SQLite é opcional lá (try/except)."""

    def connection(self):
        raise RuntimeError("histórico do Core fica no PostgreSQL")


@dataclass
class ModuleStatus:
    module: str
    licensed: bool
    kind: str | None = None
    state: str = "unlicensed"              # unlicensed|active|due_soon|overdue|suspension_scheduled|suspended|
    #                                        expired|reactivated|demo|demo_expired|demo_pending|blocked
    message: str = ""
    ends_at: datetime | None = None
    limits: dict[str, Any] = field(default_factory=dict)
    grant_id: str | None = None

    def public(self) -> dict[str, Any]:
        return {"module": self.module, "label": F.MODULE_LABELS.get(self.module, self.module),
                "licensed": self.licensed, "kind": self.kind, "state": self.state, "message": self.message,
                "ends_at": self.ends_at.isoformat() if self.ends_at else None, "limits": self.limits}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _merge_grants(recs: list[dict[str, Any]]) -> dict[str, Any]:
    """Une as cópias do cofre mantendo a ativação mais antiga de cada direito (não se "reinicia" uma
    demonstração apagando uma cópia)."""
    items: dict[str, str] = {}
    for r in recs:
        for k, v in (r.get("items") or {}).items():
            if k not in items or v < items[k]:
                items[k] = v
    best = max(recs, key=lambda r: int(r.get("seq", 0)))
    return {**best, "items": items}


# --------------------------------------------------------------------------- serviço

class Licensing:
    def __init__(self, machine: Machine, *, public_keys: dict[str, str] | None = None,
                 key_scopes: dict[str, tuple[str, ...]] | None = None, mode: str = "edge",
                 settings: Callable[[str], Any] | None = None, post=None) -> None:
        self.m = machine
        self.vault = machine.vault
        self.time = machine.time
        self.public_keys = PUBLIC_KEYS if public_keys is None else public_keys
        self.key_scopes = KEY_SCOPES if key_scopes is None else key_scopes
        self.restricted_keys = None              # None = ``keys.RESTRICTED_KEYS``
        self.mode = mode
        self.authorizations = AuthorizationBook(machine.vault, _NoSqliteHistory())
        self._settings = settings or (lambda k: None)
        self._post = post
        self._lock = threading.Lock()
        self._cache: dict[uuid.UUID, tuple[float, dict[str, ModuleStatus]]] = {}
        self._tpm_proof: tuple[float, str, bool, str] | None = None
        self._active_payload: dict[uuid.UUID, dict | None] = {}
        self._session: Session | None = None

    # -------------------------------------------------------------- identidade
    def installation_id(self) -> str:
        return self.m.installation.current().installation_id

    def profile(self, refresh: bool = False):
        return self.m.hardware.profile(refresh)

    def hardware_id(self) -> str:
        return self.profile().hardware_id

    def get(self, key: str):                      # interface usada pelo OnlineValidator do Print
        return self._settings(key)

    def _require_edge(self) -> None:
        if self.mode != "edge":
            raise ValidationFailed("O licenciamento do ambiente CLOUD (por organização, sem vínculo com um "
                                   "servidor) ainda não está disponível nesta versão.")

    # -------------------------------------------------------------- solicitação
    def request(self, *, modules: list[str], demo_days: int | None, organization: str, contact: dict[str, str],
                reason: str = "new") -> dict[str, str]:
        """Código/arquivo de solicitação para o fornecedor (inclui os módulos desejados e, se for o caso,
        o pedido de demonstração). Não concede nada: a licença vem assinada pelo License Manager."""
        self._require_edge()
        bad = [m for m in modules if m not in F.MODULE_CODES]
        if bad or not modules:
            raise ValidationFailed("Selecione módulos válidos.", details={"modules": bad})
        if demo_days is not None and not (1 <= int(demo_days) <= F.DEMO_CUSTOM_MAX_DAYS):
            raise ValidationFailed(f"Demonstração: de 1 a {F.DEMO_CUSTOM_MAX_DAYS} dias.")
        prof = self.profile(refresh=True)
        ts = self.time.check()
        data: dict[str, Any] = {
            "v": F.VERSION, "product_id": F.PRODUCT_ID, "product": "VYONIX Platform",
            "request_id": secrets.token_hex(12), "hardware_id": prof.hardware_id, "hw": prof.digests,
            "installation_id": self.installation_id(), "app_version": f"platform-{__version__}",
            "site": organization[:200] or None, "requested_at": F.iso(ts.wall),
            "reason": reason if reason in F.REACTIVATION_REASONS or reason == "new" else "other",
            "platform": {"modules": sorted(set(modules)), "demo_days": int(demo_days) if demo_days else None,
                         "contact": {k: str(v)[:200] for k, v in contact.items()
                                     if k in ("name", "email", "phone", "document", "notes")}},
        }
        if prof.tpm:
            data["tpm"] = {"alg": prof.tpm["alg"], "pub": b64e(prof.tpm["pub"])}
            try:
                data["tpm"]["sig"] = b64e(self.m.tpm.sign(hashlib.sha256(F.request_signed_part(data)).digest()))
            except Exception as exc:  # noqa: BLE001
                data["tpm"]["error"] = str(exc)[:120]
        return {"code": F.encode_request(data), "file": F.request_file(data), "request_id": data["request_id"],
                "hardware_id": prof.hardware_id, "installation_id": data["installation_id"]}

    # -------------------------------------------------------------- verificação de documentos
    def _verify_doc(self, text: str, fmt: str) -> F.SignedDoc:
        try:
            doc = F.parse_signed(text, fmt)
        except F.FormatError as exc:
            raise ValidationFailed(str(exc)) from None
        key = self.public_keys.get(doc.key_id)
        if not key:
            raise ValidationFailed(f"Documento assinado por uma chave desconhecida ({doc.key_id or '—'}).")
        if not verify_ed25519(key, doc.signed, doc.signature):
            raise ValidationFailed("Assinatura digital inválida: o documento foi alterado ou não é autêntico.")
        why = key_policy_error(doc.key_id, doc.signed, self.restricted_keys)
        if why:
            raise ValidationFailed(why)
        if F.SCOPE_OF_FORMAT.get(fmt) not in self.key_scopes.get(doc.key_id, F.ALL_SCOPES):
            raise ValidationFailed(f"A chave {doc.key_id} não está autorizada a emitir este tipo de documento.")
        if doc.payload.get("product_id") != F.PRODUCT_ID:
            raise ValidationFailed(f"Documento de outro produto ({doc.payload.get('product_id')}).")
        return doc

    def _tpm_prove(self, prof) -> tuple[bool, str]:
        if not prof.tpm:
            return False, "TPM indisponível"
        digest = prof.digests.get("tpm") or ""
        now = time.monotonic()
        c = self._tpm_proof
        if c and c[1] == digest and now - c[0] < TPM_PROOF_S:
            return c[2], c[3]
        ok, msg = tpm_mod.prove(self.m.tpm, prof.tpm["alg"], prof.tpm["pub"])
        self._tpm_proof = (now, digest, ok, msg)
        return ok, msg

    def _revoked(self) -> dict[str, str]:
        return dict((self.vault.best("revocation")[0] or {}).get("revoked") or {})

    def _binding_problem(self, p: dict[str, Any], *, refresh: bool = False) -> str | None:
        """Instalação, hardware, TPM e revogação. ``None`` = confere."""
        if p.get("installation_id") != self.installation_id():
            return ("Licença emitida para outra instalação do VYONIX (programa reinstalado ou copiado). "
                    "Gere uma nova solicitação e peça a reativação.")
        prof = self.profile(refresh)
        match = F.compare_hardware(p.get("hw") or {}, prof.digests)
        if not match.ok:
            return match.reason + " Gere uma nova solicitação e peça a reativação."
        if (p.get("hw") or {}).get("tpm"):
            ok, msg = self._tpm_prove(prof)
            if not ok:
                return f"Prova de posse do TPM falhou: {msg}."
        rv = self._revoked()
        if p.get("license_id") in rv:
            return "Licença revogada pelo fornecedor" + (f" ({rv[p['license_id']]})." if rv[p["license_id"]] else ".")
        return None

    def check(self, text: str) -> dict[str, Any]:
        """Valida uma licença sem gravar nada. Retorna o conteúdo (payload) ou levanta ``ValidationFailed``."""
        self._require_edge()
        doc = self._verify_doc(text, F.LICENSE_FORMAT)
        errors = F.validate_license_payload(doc.payload) + F.validate_modules(doc.payload)
        if errors:
            raise ValidationFailed("Licença recusada: " + "; ".join(dict.fromkeys(errors)) + ".")
        p = doc.payload
        problem = self._binding_problem(p, refresh=True)
        if problem:
            raise ValidationFailed(problem)
        ts = self.time.check(floor=F.parse_time(p["issued_at"]))
        if not ts.ok:
            raise ValidationFailed(ts.message)
        if p.get("starts_at") and ts.effective < F.parse_time(p["starts_at"]) - timedelta(hours=26):
            raise ValidationFailed(f"Licença válida somente a partir de "
                                   f"{F.parse_time(p['starts_at']).astimezone(F.BRT):%d/%m/%Y}.")
        return p

    # -------------------------------------------------------------- aplicação da licença
    def _grants(self) -> dict[str, str]:
        return dict((self.vault.best(GRANTS_RECORD, _merge_grants)[0] or {}).get("items") or {})

    def _activate_grants(self, grant_ids: list[str], now: datetime) -> dict[str, str]:
        rec = self.vault.best(GRANTS_RECORD, _merge_grants)[0] or {}
        items = dict(rec.get("items") or {})
        new = [g for g in grant_ids if g not in items]
        if new:
            for g in new:
                items[g] = F.iso(now)
            self.vault.write(GRANTS_RECORD, {**rec, "items": items})
        return items

    def install(self, s: Session, text: str, *, actor: str, actor_id=None, ip=None) -> dict[str, Any]:
        p = self.check(text)
        sha = _sha(text.strip())
        now = self.time.check().effective
        active = self._active_doc(s)
        if s.execute(select(LicenseDocument).where(LicenseDocument.sha256 == sha)).scalar_one_or_none():
            raise Conflict("Esta licença já foi aplicada.")
        if active is not None:
            ap = json.loads(active.document)
            if F.parse_time(p["issued_at"]) < F.parse_time(ap["issued_at"]):
                raise Conflict("Licença mais antiga que a instalada (reaplicação de licença anterior recusada).")
        mods = F.license_modules(p)
        contract_kind = "demo" if p["type"] == "demo" else ("permanent" if p["type"] == "permanent" else
                                                             "subscription")
        # demonstrações: prazo para ativar e registro da ativação no cofre (pelo grant_id)
        grants = self._grants()
        demo_grants = []
        for code, m in mods.items():
            g = m["grant_id"]
            if m["kind"] == "demo" or contract_kind == "demo":
                deadline = F.parse_time(m["activate_by"]) if m["kind"] == "demo" else (
                    F.parse_time(p["expires_at"]) if p.get("expires_at") else None)
                if g not in grants and deadline and now > deadline:
                    raise ValidationFailed(f"O prazo para ativar a demonstração de {F.MODULE_LABELS[code]} terminou "
                                           f"em {deadline.astimezone(F.BRT):%d/%m/%Y}. Solicite uma nova.")
                demo_grants.append(g)
        grants = self._activate_grants(demo_grants, now)

        before = {e.module: e for e in s.execute(select(Entitlement)).scalars()}
        changes: dict[str, str] = {}
        for code, m in mods.items():
            kind = "demo" if m["kind"] == "demo" else contract_kind
            e = before.pop(code, None)
            prev = (e.kind, e.grant_id, e.demo_days) if e else None
            if e is None:
                e = Entitlement(module=code, kind=kind, license_id=p["license_id"], grant_id=m["grant_id"])
                s.add(e)
            e.kind, e.license_id, e.grant_id = kind, p["license_id"], m["grant_id"]
            e.limits = {k: v for k, v in (m.get("limits") or {}).items() if v is not None}
            e.plan = p["type"] if m["kind"] == "contract" else None
            e.starts_at = F.parse_time(p["starts_at"]) if p.get("starts_at") else None
            if kind == "demo":
                act = F.parse_time(grants[m["grant_id"]])
                if m["kind"] == "demo":
                    e.demo_days, e.activate_by = int(m["days"]), F.parse_time(m["activate_by"])
                    e.ends_at = act + timedelta(days=int(m["days"]))
                else:                                   # licença DEMO inteira (formato do Print)
                    hours = int(p.get("duration_hours") or F.DEMO_HOURS)
                    e.demo_days, e.activate_by = max(1, hours // 24), (F.parse_time(p["expires_at"])
                                                                       if p.get("expires_at") else None)
                    e.ends_at = act + timedelta(hours=hours)
                e.activated_at = act
            else:
                e.demo_days = e.activate_by = e.activated_at = None
                e.ends_at = F.parse_time(p["expires_at"]) if p.get("expires_at") else None
            if prev is None:
                changes[code] = "granted"
            elif prev[0] == "demo" and kind != "demo":
                changes[code] = "converted"
            elif kind == "demo" and prev[1] == m["grant_id"] and (prev[2] or 0) < (e.demo_days or 0):
                changes[code] = "extended"
            elif prev != (e.kind, e.grant_id, e.demo_days):
                changes[code] = "changed"
        for code, e in before.items():          # módulos que saíram da licença
            s.delete(e)
            changes[code] = "removed"
        if active is not None:
            active.status = "superseded"
        s.add(LicenseDocument(kind="license", license_id=p["license_id"], seq=0, sha256=sha, document=json.dumps(p),
                              applied_by=actor, status="active"))
        s.flush()
        self._invalidate(s)
        audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="license.apply", target_type="license",
                     target_id=p["license_id"], details={"type": p["type"], "schema": p.get("schema", 2),
                                                        "modules": changes, "key_id": json.loads(text)["key_id"]})
        publish(s, "core.license.applied.v1", {"license_id": p["license_id"], "modules": changes}, source="core",
                subject_kind="license", subject_id=p["license_id"])
        return {"license_id": p["license_id"], "changes": changes, "modules": self.public_status(s)}

    def _active_doc(self, s: Session) -> LicenseDocument | None:
        return s.execute(select(LicenseDocument).where(LicenseDocument.kind == "license",
                                                       LicenseDocument.status == "active")
                         .order_by(LicenseDocument.created_at.desc()).limit(1)).scalar_one_or_none()

    def installed_payload(self, s: Session) -> dict[str, Any] | None:
        d = self._active_doc(s)
        return json.loads(d.document) if d else None

    # -------------------------------------------------------------- autorizações de uso (assinatura)
    def _lic_obj(self, p: dict[str, Any]):
        return SimpleNamespace(license_id=p["license_id"], type=p["type"], expires_at=p.get("expires_at"),
                               issued_at=p["issued_at"], hardware_id=p["hardware_id"], hw=p.get("hw") or {},
                               extra={"policy": p.get("policy")} if p.get("policy") is not None else {})

    def apply_authorization(self, text: str, *, actor: str, source: str = "file", expected_nonce: str | None = None,
                            s: Session | None = None, actor_id=None, ip=None) -> dict[str, Any]:
        s = s or self._session
        if s is None:
            raise RuntimeError("apply_authorization sem sessão")
        p_lic = self.installed_payload(s)
        if p_lic is None or p_lic["type"] == "demo":
            raise ValidationFailed("Nenhuma licença comercial instalada para receber a autorização.")
        doc = self._verify_doc(text, F.AUTHORIZATION_FORMAT)
        ts = self.time.check()
        if not ts.ok:
            raise ValidationFailed(ts.message)
        try:
            p = self.authorizations.apply(doc, text, lic=self._lic_obj(p_lic), hardware_digests=self.profile(True).digests,
                                          installation_id=self.installation_id(), now=ts.effective, actor=actor,
                                          expected_nonce=expected_nonce)
        except _PrintValidationError as exc:
            audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="license.authorization_rejected",
                         details={"source": source, "reason": str(exc)[:300]})
            raise ValidationFailed(str(exc)) from None
        if p.get("revoked"):
            cur = self.vault.best("revocation")[0] or {}
            self.vault.write("revocation", {**cur, "revoked": {**(cur.get("revoked") or {}),
                                                               p["license_id"]: str(p["revoked"])}})
        s.add(LicenseDocument(kind="authorization", license_id=p["license_id"], seq=int(p["seq"]),
                              sha256=_sha(text.strip()), document=json.dumps(p), applied_by=actor, status="active"))
        s.flush()
        self._invalidate(s)
        audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="license.authorization", target_type="license",
                     target_id=p["license_id"], details={"authorization_id": p["authorization_id"], "seq": p["seq"],
                                                        "source": source, "state": p["commercial"].get("state"),
                                                        "valid_until": p["valid_until"]})
        return p

    def installed_license(self):                  # interface do OnlineValidator
        p = self.installed_payload(self._session) if self._session is not None else None
        return self._lic_obj(p) if p else None

    def record_online(self, kind: str, message: str, *, actor: str, authorization: dict | None = None):
        from app.licensing.online import OnlineResult
        now = F.iso(datetime.now(timezone.utc))
        vals = {"result": kind, "message": message if kind != "ok" else "", "last_attempt": now}
        if kind == "ok":
            vals["last_ok"] = now
        self.authorizations.set_online(**vals)
        if self._session is not None:
            audit.record(self._session, actor=actor, action=f"license.online.{kind}",
                         details={"message": message[:300]})
            self._invalidate(self._session)
        return OnlineResult(kind, message, authorization)

    def check_online(self, s: Session, *, actor: str) -> dict[str, Any]:
        """Consulta o VYONIX License Server (licenças com validação online)."""
        from app.licensing.online import OnlineValidator
        p = self.installed_payload(s)
        if p is None or p["type"] == "demo":
            raise ValidationFailed("Nenhuma licença comercial instalada.")
        if F.license_policy(p)["validation"] != "online":
            raise ValidationFailed("Esta licença é offline: a renovação é feita por arquivo (.vyauth).")
        self._session = s
        try:
            r = OnlineValidator(self, self._post).check(actor=actor)
        except _PrintValidationError as exc:
            raise ValidationFailed(str(exc)) from None
        finally:
            self._session = None
        return {"result": r.result, "label": CONNECTIVITY_LABELS.get(r.result, r.result), "message": r.message}

    # -------------------------------------------------------------- situação
    def _invalidate(self, s: Session | None = None) -> None:
        with self._lock:
            if s is not None and s.info.get("tenant_id"):
                self._cache.pop(s.info["tenant_id"], None)
            else:
                self._cache.clear()

    def status(self, s: Session, *, refresh: bool = False) -> dict[str, ModuleStatus]:
        tid = s.info.get("tenant_id")
        with self._lock:
            c = self._cache.get(tid)
            if c and not refresh and time.monotonic() - c[0] < CACHE_S:
                return c[1]
        out = self._compute(s)
        with self._lock:
            self._cache[tid] = (time.monotonic(), out)
        return out

    def _compute(self, s: Session) -> dict[str, ModuleStatus]:
        out = {code: ModuleStatus(code, False, message="Sem licença para este módulo.")
               for code in F.MODULE_CODES}
        out["core"].limits = dict(UNLICENSED_CORE_LIMITS)
        out["core"].message = (f"Sem licença: uso limitado a {UNLICENSED_CORE_LIMITS['users']} usuários e "
                               f"{UNLICENSED_CORE_LIMITS['sites']} unidade, para instalar a licença.")
        ents = list(s.execute(select(Entitlement)).scalars())
        p = self.installed_payload(s)
        if not ents or p is None:
            return out
        if self.mode != "edge":
            for e in ents:
                out[e.module] = ModuleStatus(e.module, False, e.kind, "blocked", "Licenciamento CLOUD indisponível.")
            return out
        ts = self.time.check()
        problem = self._binding_problem(p) or (None if ts.ok else ts.message)
        now = ts.effective
        commercial = None
        if p["type"] != "demo":
            commercial = self.authorizations.evaluate(self._lic_obj(p), now)
        for e in ents:
            st = ModuleStatus(e.module, False, e.kind, limits=dict(e.limits or {}), grant_id=e.grant_id,
                              ends_at=e.ends_at)
            if problem:
                st.state, st.message = "blocked", problem
            elif e.kind == "demo":
                if e.ends_at and now >= e.ends_at:
                    st.state = "demo_expired"
                    st.message = f"Demonstração encerrada em {e.ends_at.astimezone(F.BRT):%d/%m/%Y %H:%M}."
                else:
                    st.licensed, st.state = True, "demo"
                    left = e.ends_at - now
                    st.message = (f"Demonstração: {left.days} dia(s) e {left.seconds // 3600} h restantes "
                                  f"(até {e.ends_at.astimezone(F.BRT):%d/%m/%Y %H:%M}).")
            else:
                ev = commercial.evaluation
                st.state = ev.state.value
                st.ends_at = ev.due_at or e.ends_at
                if commercial.revoked:
                    st.state, st.message = "blocked", f"Licença revogada ({commercial.revoked})."
                elif commercial.auth_expired_since is not None:
                    st.state = "auth_expired"
                    st.message = ("Validação online pendente: sem autorização renovada do License Server desde "
                                  f"{commercial.auth_expired_since.astimezone(F.BRT):%d/%m/%Y %H:%M}. "
                                  + commercial.connectivity_detail).strip()
                elif ev.state.restricts:
                    st.message = ev.admin_message or ev.state.label
                else:
                    st.licensed = True
                    st.message = ev.state.label + (f" — {ev.admin_message}" if ev.admin_message else "")
            if e.module == "core" and not st.licensed:
                st.limits = {**dict(UNLICENSED_CORE_LIMITS)}
            out[e.module] = st
        return out

    def module_ok(self, s: Session, code: str) -> tuple[bool, str]:
        st = self.status(s).get(code)
        return (bool(st and st.licensed), st.message if st else "Módulo desconhecido.")

    def require_module(self, s: Session, code: str) -> None:
        ok, msg = self.module_ok(s, code)
        if not ok:
            raise NotLicensed(msg)

    def enforce_limit(self, s: Session, module: str, key: str, wanted: int) -> None:
        st = self.status(s).get(module)
        lim = (st.limits or {}).get(key) if st else None
        if lim is not None and wanted > int(lim):
            label = {"users": "usuários ativos", "sites": "unidades"}.get(key, key)
            raise NotLicensed(f"Limite da licença atingido: {lim} {label}. Solicite a ampliação ao fornecedor.",
                              details={"module": module, "limit": key, "max": lim})

    def public_status(self, s: Session, *, refresh: bool = False) -> dict[str, Any]:
        st = self.status(s, refresh=refresh)
        p = self.installed_payload(s)
        pol = F.license_policy(p) if p else None
        on = self.authorizations.online() if p else {}
        return {
            "installation_id": self.installation_id(), "hardware_id": self.hardware_id(), "mode": self.mode,
            "license": None if p is None else {
                "license_id": p["license_id"], "type": p["type"],
                "type_label": F.LICENSE_TYPES.get(p["type"], (p["type"],))[0], "edition": p.get("edition"),
                "customer": (p.get("customer") or {}).get("name") if isinstance(p.get("customer"), dict)
                else p.get("customer"),
                "issued_at": p["issued_at"], "expires_at": p.get("expires_at"), "schema": p.get("schema", 2),
                "validation": pol["validation"], "connectivity": on.get("result") or (
                    "offline" if pol["validation"] == "offline" else "pending"),
                "connectivity_label": CONNECTIVITY_LABELS.get(on.get("result") or "", ""),
                "last_online_ok": on.get("last_ok"),
            },
            "modules": [st[c].public() for c in F.MODULE_CODES],
        }

    def documents(self, s: Session, limit: int = 50) -> list[dict[str, Any]]:
        return [{"kind": d.kind, "license_id": d.license_id, "seq": d.seq, "status": d.status,
                 "applied_by": d.applied_by, "applied_at": d.created_at.isoformat()}
                for d in s.execute(select(LicenseDocument).order_by(LicenseDocument.created_at.desc()).limit(limit))
                .scalars()]


def count_active_users(s: Session) -> int:
    from vyonix.auth.models import User
    return int(s.execute(select(func.count()).select_from(User).where(User.active.is_(True))).scalar())


def count_sites(s: Session) -> int:
    from vyonix.tenancy.models import Site
    return int(s.execute(select(func.count()).select_from(Site).where(Site.active.is_(True))).scalar())


def env_isolated() -> bool:
    return os.environ.get("VYONIX_LICENSING_ISOLATED") == "1"
