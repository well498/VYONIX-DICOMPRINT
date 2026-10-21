"""Formatos do licenciamento VYONIX (versão 2).

Documentos assinados (licença, revalidação de horário, lista de revogação) usam o envelope::

    {"format": "<tipo>", "v": 2, "key_id": "<chave emissora>",
     "payload": "<base64url(JSON canônico)>", "signature": "<base64url(Ed25519)>"}

A assinatura cobre exatamente os bytes de ``payload``. Nenhum documento é aceito apenas por ter o
nome ou a estrutura corretos: a assinatura, a chave emissora (lista de chaves públicas embutida no
VYONIX DICOM Print), o produto, o Hardware ID, o Installation ID e a validade são conferidos.

A **solicitação de ativação** (``VYXR2-…``) não é assinada pelo fornecedor; quando o computador
tem TPM, ela é assinada pela chave do TPM (prova de posse verificada no License Manager).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

from vyonix_protocol.codec import b64d, b64e, canonical, check_code

PRODUCT_ID = "VYONIX-DICOM-PRINT"
PRODUCT_NAME = "VYONIX DICOM Print"
VERSION = 2

REQUEST_PREFIX = "VYXR2-"
LICENSE_FORMAT = "vyonix-license"
REVALIDATION_FORMAT = "vyonix-revalidation"
REVOCATION_FORMAT = "vyonix-revocation"
DIAGNOSTIC_FORMAT = "vyonix-diagnostic"
REQUEST_FILE_FORMAT = "vyonix-request"

FEATURES = ("storage", "printing", "print_scp", "rules")
FEATURE_LABELS = {"storage": "Recepção DICOM (C-STORE SCP)", "printing": "Impressão e fila",
                  "print_scp": "Impressão DICOM (Print SCP)", "rules": "Regras automáticas"}

# tipo → (rótulo, meses, horas). Meses/horas None = sem cálculo automático.
LICENSE_TYPES: dict[str, tuple[str, int | None, int | None]] = {
    "demo": ("DEMO — 5 dias (120 horas)", None, 120),
    "monthly": ("Mensal", 1, None),
    "quarterly": ("Trimestral", 3, None),
    "semiannual": ("Semestral", 6, None),
    "annual": ("Anual", 12, None),
    "permanent": ("Permanente", None, None),
    "custom": ("Personalizada", None, None),
}
DEMO_HOURS = 120
DEMO_ACTIVATE_WITHIN_DAYS = 30

# Componentes do VYONIX Hardware ID. "mac" é auxiliar (lista) e não entra no ID.
HW_STRONG = ("uuid", "board", "system", "disk", "tpm")
HW_LABELS = {"uuid": "UUID do computador (SMBIOS)", "board": "Placa-mãe", "system": "Identificador do Windows",
             "disk": "Disco do sistema", "tpm": "Chave do TPM 2.0", "mac": "Placa de rede física"}
HW_CHANGE_TEXT = {"uuid": "computador diferente (UUID)", "board": "placa-mãe diferente",
                  "system": "Windows reinstalado ou outro computador", "disk": "disco do sistema substituído",
                  "tpm": "TPM diferente ou chave do TPM removida"}

REACTIVATION_REASONS = {
    "disk": "Substituição de HD/SSD", "board": "Troca de placa-mãe", "computer": "Substituição do computador",
    "windows": "Reinstalação do Windows", "reinstall": "Desinstalação e reinstalação do VYONIX",
    "storage_failure": "Falha de armazenamento", "system_recovery": "Recuperação de sistema",
    "time": "Revalidação de data e hora", "other": "Outro motivo",
}

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class FormatError(ValueError):
    """Documento ilegível ou fora do formato."""


# ---------------------------------------------------------------------------- Hardware ID
def hardware_id(digests: dict[str, Any]) -> str:
    """``VYXH-XXXXX-XXXXX-XXXXX-XXXXX``: resumo dos componentes fortes disponíveis."""
    parts = {k: digests[k] for k in HW_STRONG if isinstance(digests.get(k), str) and digests.get(k)}
    raw = hashlib.sha256(b"VYONIX/hardware-id/v2|" + canonical(parts)).digest()
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"         # Crockford base32 (sem I, L, O, U)
    n = int.from_bytes(raw[:13], "big")
    chars = []
    for _ in range(20):
        n, r = divmod(n, 32)
        chars.append(alphabet[r])
    s = "".join(reversed(chars))
    return "VYXH-" + "-".join(s[i:i + 5] for i in range(0, 20, 5))


@dataclass
class HardwareMatch:
    ok: bool
    matched: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    mac_ok: bool = False
    reason: str = ""


def compare_hardware(authorized: dict[str, Any], current: dict[str, Any]) -> HardwareMatch:
    """Compara os componentes autorizados (licença) com os atuais.

    Regras: nenhum componente forte pode estar **diferente**; pelo menos dois precisam
    coincidir (ou todos, se a licença tiver menos de dois); no máximo um componente pode estar
    **ilegível** agora, e só se uma placa de rede física autorizada também estiver presente. A chave
    do TPM, quando autorizada, precisa estar presente (a prova de posse é verificada à parte).
    """
    m = HardwareMatch(ok=False)
    for c in HW_STRONG:
        a = authorized.get(c)
        if not a:
            continue
        cur = current.get(c)
        if not cur:
            m.missing.append(c)
        elif cur == a:
            m.matched.append(c)
        else:
            m.changed.append(c)
    macs_a, macs_c = set(authorized.get("mac") or []), set(current.get("mac") or [])
    m.mac_ok = bool(macs_a & macs_c)
    total = len(m.matched) + len(m.changed) + len(m.missing)
    need = min(2, total) if total else 1
    if m.changed:
        m.reason = "Licença de outro computador: " + ", ".join(HW_CHANGE_TEXT[c] for c in m.changed) + "."
    elif "tpm" in m.missing:
        m.reason = "A chave do TPM autorizada não está disponível neste computador."
    elif len(m.missing) > 1 or (m.missing and not m.mac_ok):
        m.reason = ("Não foi possível confirmar o computador: componentes ilegíveis ("
                    + ", ".join(HW_LABELS[c] for c in m.missing) + ").")
    elif len(m.matched) < need:
        m.reason = "Componentes de hardware insuficientes para confirmar o computador."
    else:
        m.ok = True
    return m


# ---------------------------------------------------------------------------- solicitação
REQUEST_REQUIRED = ("v", "product_id", "request_id", "hardware_id", "hw", "installation_id", "requested_at")


def encode_request(data: dict[str, Any]) -> str:
    body = canonical(data)
    return REQUEST_PREFIX + b64e(body) + "." + check_code(body)


def request_file(data: dict[str, Any]) -> str:
    """Conteúdo do arquivo ``.vyreq`` (o código + um resumo legível)."""
    return json.dumps({"format": REQUEST_FILE_FORMAT, "v": VERSION, "code": encode_request(data),
                       "summary": {"product": PRODUCT_NAME, "hardware_id": data.get("hardware_id"),
                                   "installation_id": data.get("installation_id"),
                                   "site": data.get("site"), "requested_at": data.get("requested_at")}},
                      ensure_ascii=False, indent=2)


def parse_request(text: str) -> dict[str, Any]:
    """Aceita o código ``VYXR2-…`` ou o conteúdo de um arquivo ``.vyreq``."""
    text = (text or "").strip()
    if text.startswith("{"):
        try:
            doc = json.loads(text)
        except ValueError as exc:
            raise FormatError("Arquivo de solicitação ilegível.") from exc
        if doc.get("format") != REQUEST_FILE_FORMAT:
            raise FormatError("O arquivo não é uma solicitação de ativação do VYONIX.")
        text = str(doc.get("code", ""))
    code = "".join(text.split())
    if code.startswith("VYXR1-"):
        raise FormatError("Solicitação do formato antigo (VYXR1). Atualize o VYONIX DICOM Print e gere uma nova.")
    if not code.startswith(REQUEST_PREFIX):
        raise FormatError("Código de solicitação inválido (deve começar com VYXR2-).")
    body_txt, _, chk = code[len(REQUEST_PREFIX):].partition(".")
    try:
        body = b64d(body_txt)
    except Exception as exc:  # noqa: BLE001
        raise FormatError("Código de solicitação ilegível (copiado pela metade?).") from exc
    if chk and chk.upper() != check_code(body):
        raise FormatError("Código de solicitação com erro de cópia (dígitos de conferência não conferem).")
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise FormatError(f"Código de solicitação ilegível: {exc}") from exc
    missing = [k for k in REQUEST_REQUIRED if not data.get(k)]
    if missing:
        raise FormatError("Solicitação incompleta: " + ", ".join(missing) + ".")
    if data.get("product_id") != PRODUCT_ID:
        raise FormatError(f"Solicitação de outro produto ({data.get('product_id')}).")
    if hardware_id(data["hw"]) != data["hardware_id"]:
        raise FormatError("Solicitação inconsistente: o Hardware ID não corresponde aos componentes.")
    return data


def request_signed_part(data: dict[str, Any]) -> bytes:
    """Bytes cobertos pela assinatura do TPM na solicitação (tudo menos ``tpm.sig``)."""
    d = json.loads(json.dumps(data))
    if isinstance(d.get("tpm"), dict):
        d["tpm"].pop("sig", None)
    return canonical(d)


# ---------------------------------------------------------------------------- documentos assinados
def build_signed(fmt: str, payload: dict[str, Any], key_id: str, sign: Callable[[bytes], bytes]) -> str:
    body = canonical(payload)
    doc = {"format": fmt, "v": VERSION, "key_id": key_id, "payload": b64e(body), "signature": b64e(sign(body))}
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


@dataclass
class SignedDoc:
    fmt: str
    payload: dict[str, Any]
    signed: bytes
    signature: bytes
    key_id: str


def parse_signed(text: str, expected: str | Iterable[str]) -> SignedDoc:
    exp = {expected} if isinstance(expected, str) else set(expected)
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise FormatError("Arquivo inválido (não é JSON).") from exc
    if not isinstance(doc, dict) or doc.get("format") not in exp:
        raise FormatError("O arquivo não é um documento VYONIX do tipo esperado.")
    if doc.get("v") != VERSION:
        raise FormatError("Documento de formato antigo. Solicite um novo ao administrador.")
    try:
        signed = b64d(doc["payload"])
        signature = b64d(doc["signature"])
        payload = json.loads(signed.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise FormatError(f"Documento corrompido: {exc}") from exc
    if not isinstance(payload, dict):
        raise FormatError("Documento corrompido.")
    return SignedDoc(doc["format"], payload, signed, signature, str(doc.get("key_id", "")))


LICENSE_REQUIRED = ("license_id", "product_id", "type", "edition", "customer", "hardware_id", "hw",
                    "installation_id", "issued_at", "features")


def validate_license_payload(p: dict[str, Any]) -> list[str]:
    errors = [f"campo ausente: {k}" for k in LICENSE_REQUIRED if p.get(k) in (None, "", {})]
    if p.get("type") and p["type"] not in LICENSE_TYPES:
        errors.append(f"tipo de licença desconhecido: {p['type']}")
    if not isinstance(p.get("features", []), list):
        errors.append("recursos inválidos")
    for k in ("issued_at", "starts_at", "expires_at"):
        if p.get(k):
            try:
                parse_time(p[k])
            except ValueError:
                errors.append(f"data inválida em {k}")
    if p.get("type") == "demo" and not p.get("duration_hours"):
        errors.append("DEMO sem duração")
    if isinstance(p.get("hw"), dict) and p.get("hardware_id") and hardware_id(p["hw"]) != p["hardware_id"]:
        errors.append("Hardware ID não corresponde aos componentes")
    return errors


# ---------------------------------------------------------------------------- datas
BRT = timezone(timedelta(hours=-3))


def parse_time(value: str) -> datetime:
    v = str(value).strip()
    if len(v) == 10:                                 # AAAA-MM-DD: fim do dia, horário de Brasília
        d = datetime.fromisoformat(v)
        return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=BRT).astimezone(timezone.utc)
    dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_months(start: datetime, months: int) -> datetime:
    """Fim do período: mesmo dia do mês seguinte menos um segundo (23:59:59 de Brasília do dia anterior)."""
    local = start.astimezone(BRT)
    y, mth = divmod(local.month - 1 + months, 12)
    year, month = local.year + y, mth + 1
    import calendar
    day = min(local.day, calendar.monthrange(year, month)[1])
    end = datetime(year, month, day, 0, 0, 0, tzinfo=BRT) - timedelta(seconds=1)
    return end.astimezone(timezone.utc)


def compute_expiry(ltype: str, start: datetime, custom_end: datetime | None = None) -> datetime | None:
    label, months, hours = LICENSE_TYPES[ltype]
    if ltype == "permanent":
        return None
    if ltype == "custom":
        if custom_end is None:
            raise ValueError("Licença personalizada: informe a data de vencimento.")
        return custom_end
    if hours:
        return start + timedelta(hours=hours)
    return add_months(start, int(months))
