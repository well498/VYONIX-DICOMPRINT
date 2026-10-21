"""Licenciamento offline (Fase 8) — implementa ``core.contracts.LicenseValidator``.

Fluxo:

1. O cliente gera o **código de solicitação** (página Licença). Ele contém o ID da instalação, o
   identificador do computador (hash, ver ``machine.py``), a versão e o nome da unidade — nada de
   dados de pacientes.
2. O fornecedor emite a licença com a ferramenta separada ``license_admin`` (chave privada Ed25519,
   que nunca acompanha o aplicativo).
3. O cliente instala o arquivo ``.vylic``. O VYONIX verifica a assinatura com a chave pública
   embutida, o produto, a instalação, o computador e a validade — a cada verificação, não só na
   instalação (um registro adulterado no banco é detectado).

Política (``enforced``): nas versões de desenvolvimento/homologação (``.devN``) a licença é
verificada e exibida, mas nada é limitado. Nas versões comerciais, sem licença válida o VYONIX
funciona em **modo de avaliação** (páginas impressas com a marca "NÃO LICENCIADO") e os recursos
são limitados à edição licenciada (Print SCP, regras, número de equipamentos).
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from app import __version__, brand
from app.core.contracts import LicenseState, LicenseStatus
from app.core.errors import ValidationError
from app.database.connection import Database
from app.database.repositories.events_repo import Category, EventRepository
from app.licensing import ed25519
from app.licensing.keys import PUBLIC_KEYS
from app.licensing.machine import machine_id as current_machine_id
from app.utils.timeutil import utc_now, utc_now_iso

FORMAT = "vyonix-license"
REQUEST_PREFIX = "VYXR1-"
PRODUCT = "VYONIX DICOM Print"
ALL_FEATURES = ("storage", "printing", "print_scp", "rules")
FEATURE_LABELS = {"storage": "Recepção DICOM (Storage SCP)", "printing": "Impressão e fila",
                  "print_scp": "Impressão DICOM (Print SCP)", "rules": "Regras automáticas"}
EVALUATION_MARK = "NÃO LICENCIADO — USO PARA AVALIAÇÃO"
CLOCK_TOLERANCE = timedelta(hours=24)
CACHE_S = 60.0


def b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64d(text: str) -> bytes:
    text = "".join(str(text).split())
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def canonical(obj: dict) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def parse_request(code: str) -> dict:
    code = "".join(str(code).split())
    if not code.startswith(REQUEST_PREFIX):
        raise ValidationError("Código de solicitação inválido (deve começar com VYXR1-).")
    try:
        data = json.loads(b64d(code[len(REQUEST_PREFIX):]).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(f"Código de solicitação ilegível: {exc}") from exc
    for k in ("installation_id", "machine_id", "product"):
        if not data.get(k):
            raise ValidationError(f"Código de solicitação sem {k}.")
    return data


@dataclass
class LicenseData:
    license_id: str
    product: str
    edition: str
    licensee: str
    installation_id: str
    machine_id: str
    features: list[str]
    issued_at: str
    expires_at: str | None = None          # data (AAAA-MM-DD), inclusive; None = sem vencimento
    max_devices: int | None = None
    document: str | None = None
    notes: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, p: dict) -> "LicenseData":
        known = {f for f in cls.__dataclass_fields__ if f != "extra"}
        missing = [k for k in ("license_id", "product", "edition", "licensee", "installation_id", "machine_id",
                               "features", "issued_at") if not p.get(k) and k != "features"]
        if missing:
            raise ValidationError(f"Licença sem os campos: {', '.join(missing)}.")
        return cls(**{k: p.get(k) for k in known if k in p}, extra={k: v for k, v in p.items() if k not in known})

    def expiry_date(self) -> date | None:
        return date.fromisoformat(self.expires_at) if self.expires_at else None


def parse_license(text: str) -> tuple[dict, bytes, bytes, str]:
    """Lê o arquivo .vylic: (payload, bytes assinados, assinatura, key_id)."""
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise ValidationError("Arquivo de licença inválido (não é JSON).") from exc
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise ValidationError("O arquivo não é uma licença do VYONIX.")
    try:
        signed = b64d(doc["payload"])
        signature = b64d(doc["signature"])
        payload = json.loads(signed.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(f"Licença corrompida: {exc}") from exc
    return payload, signed, signature, str(doc.get("key_id", ""))


def verify_signature(signed: bytes, signature: bytes, key_id: str) -> bool:
    key_hex = PUBLIC_KEYS.get(key_id)
    if not key_hex:
        return False
    return ed25519.verify(bytes.fromhex(key_hex), signed, signature)


def enforced_default() -> bool:
    flag = os.environ.get("VYONIX_LICENSE_ENFORCE")
    if flag is not None:
        return flag == "1"
    return ".dev" not in __version__


class LicenseService:
    def __init__(self, db: Database, events: EventRepository, settings_get: Callable[[str], Any], *,
                 enforced: bool | None = None, machine_id: Callable[[], str] = current_machine_id,
                 clock: Callable[[], datetime] = utc_now) -> None:
        self.db = db
        self.events = events
        self.get = settings_get
        self.enforced = enforced_default() if enforced is None else enforced
        self._machine_id = machine_id
        self.clock = clock
        self._lock = threading.Lock()
        self._cache: tuple[float, LicenseStatus, LicenseData | None] | None = None

    # ------------------------------------------------------------------ solicitação
    def machine_id(self) -> str:
        return self._machine_id()

    def request_code(self) -> str:
        data = {"v": 1, "product": PRODUCT, "installation_id": self.get("system.installation_id"),
                "machine_id": self.machine_id(), "app_version": __version__,
                "site": self.get("site.name") or None, "requested_at": utc_now_iso()}
        return REQUEST_PREFIX + b64e(canonical(data))

    # ------------------------------------------------------------------ verificação
    def check(self, text: str, now: datetime | None = None) -> tuple[LicenseStatus, LicenseData | None]:
        """Valida um texto de licença sem gravar nada."""
        inst = self.get("system.installation_id")
        try:
            payload, signed, signature, key_id = parse_license(text)
        except ValidationError as exc:
            return LicenseStatus(LicenseState.INVALID, inst, message=str(exc)), None
        if not verify_signature(signed, signature, key_id):
            msg = ("assinatura digital inválida (arquivo alterado ou emitido por outra chave)"
                   if key_id in PUBLIC_KEYS else f"chave de assinatura desconhecida: {key_id or '—'}")
            return LicenseStatus(LicenseState.INVALID, inst, message=f"Licença recusada: {msg}."), None
        try:
            lic = LicenseData.from_payload(payload)
        except (ValidationError, TypeError) as exc:
            return LicenseStatus(LicenseState.INVALID, inst, message=str(exc)), None
        base = dict(installation_id=inst, edition=lic.edition, features=tuple(lic.features))
        if lic.product != PRODUCT:
            return LicenseStatus(LicenseState.INVALID, message=f"Licença de outro produto ({lic.product}).",
                                 **base), lic
        if lic.installation_id != inst:
            return LicenseStatus(LicenseState.INVALID, message="Licença emitida para outra instalação do VYONIX "
                                 f"(ID {lic.installation_id}).", **base), lic
        if lic.machine_id != self.machine_id():
            return LicenseStatus(LicenseState.HARDWARE_MISMATCH,
                                 message="Licença emitida para outro computador (o Windows foi reinstalado ou o "
                                         "VYONIX foi copiado). Solicite uma nova licença.", **base), lic
        expiry = lic.expiry_date()
        exp_dt = datetime.combine(expiry, datetime.max.time(), tzinfo=timezone.utc) if expiry else None
        now = now or self.clock()
        if exp_dt and now > exp_dt:
            return LicenseStatus(LicenseState.EXPIRED, expires_at=exp_dt,
                                 message=f"Licença vencida em {expiry.strftime('%d/%m/%Y')}.", **base), lic
        return LicenseStatus(LicenseState.VALID, expires_at=exp_dt,
                             message=f"Licença {lic.edition} para {lic.licensee}"
                                     + (f", válida até {expiry.strftime('%d/%m/%Y')}" if expiry else ", sem vencimento")
                                     + ".", **base), lic

    def _clock_ok(self, now: datetime) -> bool:
        """Detecta relógio atrasado: o horário atual não pode ficar muito antes do maior já visto."""
        conn = self.db.connection()
        r = conn.execute("SELECT value FROM license_state WHERE key = 'high_water'").fetchone()
        high = datetime.fromisoformat(r["value"]) if r else None
        if high is not None and now < high - CLOCK_TOLERANCE:
            return False
        if high is None or now > high:
            conn.execute("""INSERT INTO license_state(key, value, updated_at) VALUES ('high_water', ?, ?)
                            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
                         (now.isoformat(), utc_now_iso()))
        return True

    def status(self, *, refresh: bool = False) -> LicenseStatus:
        return self._status(refresh)[0]

    def _status(self, refresh: bool = False) -> tuple[LicenseStatus, LicenseData | None]:
        with self._lock:
            if self._cache and not refresh and time.monotonic() - self._cache[0] < CACHE_S:
                return self._cache[1], self._cache[2]
        inst = self.get("system.installation_id")
        row = self.db.connection().execute(
            "SELECT raw FROM licenses WHERE status = 'active' ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            st, lic = LicenseStatus(LicenseState.NOT_ACTIVATED, inst, message="Nenhuma licença instalada."), None
        else:
            now = self.clock()
            st, lic = self.check(row["raw"], now)
            if st.state == LicenseState.VALID and st.expires_at is not None and not self._clock_ok(now):
                st = LicenseStatus(LicenseState.INVALID, inst, edition=st.edition, features=st.features,
                                   expires_at=st.expires_at,
                                   message="O relógio do computador está atrasado em relação ao último uso. Corrija a "
                                           "data e a hora do Windows.")
            elif st.expires_at is not None:
                self._clock_ok(now)
        with self._lock:
            self._cache = (time.monotonic(), st, lic)
        return st, lic

    def license_data(self) -> LicenseData | None:
        return self._status()[1]

    # ------------------------------------------------------------------ política
    def evaluation_mode(self) -> bool:
        return self.enforced and self.status().state != LicenseState.VALID

    def allows(self, feature: str) -> bool:
        if not self.enforced:
            return True
        st, lic = self._status()
        if st.state != LicenseState.VALID or lic is None:
            # Avaliação: tudo funciona, com marca nas impressões.
            return True
        return feature in lic.features

    def device_limit(self) -> int | None:
        if not self.enforced:
            return None
        st, lic = self._status()
        if st.state != LicenseState.VALID or lic is None:
            return None
        return lic.max_devices

    def policy_text(self) -> str:
        if not self.enforced:
            return "Versão de desenvolvimento/homologação: a licença é verificada e exibida, mas nenhum recurso é limitado."
        if self.evaluation_mode():
            return ("Modo de avaliação: todos os recursos funcionam e as páginas impressas recebem a marca "
                    f"“{EVALUATION_MARK}”.")
        return "Recursos limitados à edição licenciada."

    # ------------------------------------------------------------------ instalação
    def install(self, text: str, *, actor: str) -> LicenseStatus:
        st, lic = self.check(text)
        if st.state != LicenseState.VALID or lic is None:
            self.events.add(level="WARNING", category=Category.LICENSE, action="license.rejected",
                            message=f"Licença recusada: {st.message}", actor=actor)
            raise ValidationError(st.message)
        conn = self.db.connection()
        now = utc_now_iso()
        with self.db.transaction():
            conn.execute("UPDATE licenses SET status = 'superseded' WHERE status = 'active'")
            conn.execute(
                """INSERT INTO licenses(license_id, edition, features_json, licensee, installation_id, issued_at,
                       expires_at, signature, raw, status, installed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
                   ON CONFLICT(license_id) DO UPDATE SET status = 'active', raw = excluded.raw,
                       installed_at = excluded.installed_at""",
                (lic.license_id, lic.edition, json.dumps(lic.features), lic.licensee, lic.installation_id,
                 lic.issued_at, lic.expires_at, json.loads(text)["signature"], text, now))
            self.events.add(level="INFO", category=Category.LICENSE, action="license.install",
                            message=f"Licença {lic.edition} instalada ({lic.licensee}"
                                    + (f", até {lic.expires_at}" if lic.expires_at else "") + ").", actor=actor,
                            details={"license_id": lic.license_id, "features": lic.features})
        with self._lock:
            self._cache = None
        return self.status(refresh=True)

    def remove(self, *, actor: str) -> None:
        with self.db.transaction():
            self.db.connection().execute("UPDATE licenses SET status = 'superseded' WHERE status = 'active'")
            self.events.add(level="WARNING", category=Category.LICENSE, action="license.remove",
                            message="Licença removida desta instalação.", actor=actor)
        with self._lock:
            self._cache = None

    def history(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.connection().execute(
            """SELECT license_id, edition, licensee, issued_at, expires_at, status, installed_at
               FROM licenses ORDER BY id DESC""")]


def new_license_id() -> str:
    return f"VYX-{date.today():%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"


__all__ = ["LicenseService", "LicenseData", "parse_request", "parse_license", "canonical", "b64e", "b64d",
           "FORMAT", "PRODUCT", "ALL_FEATURES", "FEATURE_LABELS", "EVALUATION_MARK", "new_license_id", "brand"]
