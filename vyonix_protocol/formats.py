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
AUTHORIZATION_FORMAT = "vyonix-authorization"     # autorização de uso (assinatura comercial), online ou arquivo

# Escopo de cada chave de emissão: uma chave só é aceita para os documentos do seu escopo. A chave
# do VYONIX License Server assina apenas autorizações de uso — mesmo que vaze, não emite licenças.
SCOPE_OF_FORMAT = {LICENSE_FORMAT: "license", AUTHORIZATION_FORMAT: "authorization",
                   REVALIDATION_FORMAT: "revalidation", REVOCATION_FORMAT: "revocation"}
ALL_SCOPES = ("license", "authorization", "revalidation", "revocation")

# Política comercial gravada (assinada) na licença.
VALIDATION_MODES = {"offline": "Offline (arquivos de renovação)", "online": "Online (VYONIX License Server)"}
DEFAULT_POLICY = {"validation": "offline", "warn_days": 5, "grace_days": 7, "online_tolerance_days": 10,
                  "server_url": None, "server_pin": None}
LEGACY_POLICY = {"validation": "offline", "warn_days": 15, "grace_days": 0, "online_tolerance_days": 0,
                 "server_url": None, "server_pin": None}       # licenças emitidas antes da revisão 4


def license_policy(payload: dict[str, Any]) -> dict[str, Any]:
    """Política efetiva de uma licença (licenças antigas, sem política, mantêm o comportamento anterior)."""
    pol = payload.get("policy")
    if not isinstance(pol, dict):
        return dict(LEGACY_POLICY)
    out = dict(DEFAULT_POLICY)
    out.update({k: v for k, v in pol.items() if k in DEFAULT_POLICY})
    for k in ("warn_days", "grace_days", "online_tolerance_days"):
        out[k] = max(0, min(365, int(out.get(k) or 0)))
    if out["validation"] not in VALIDATION_MODES:
        out["validation"] = "offline"
    return out


AUTHORIZATION_REQUIRED = ("authorization_id", "license_id", "product_id", "installation_id", "hardware_id", "seq",
                          "issued_at", "valid_until", "commercial", "source")


def validate_authorization_payload(p: dict[str, Any]) -> list[str]:
    errors = [f"campo ausente: {k}" for k in AUTHORIZATION_REQUIRED if p.get(k) in (None, "", {})]
    for k in ("issued_at", "valid_until"):
        if p.get(k):
            try:
                parse_time(p[k])
            except ValueError:
                errors.append(f"data inválida em {k}")
    com = p.get("commercial")
    if isinstance(com, dict):
        if not com.get("permanent") and not com.get("paid_until"):
            errors.append("autorização sem período pago")
    elif com is not None:
        errors.append("situação comercial inválida")
    if p.get("source") not in (None, "server", "manager"):
        errors.append("origem desconhecida")
    try:
        int(p.get("seq") or 0)
    except (TypeError, ValueError):
        errors.append("sequência inválida")
    return errors

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


# ---------------------------------------------------------------------------- módulos (licença v3)
# A licença v3 é o mesmo documento ``vyonix-license`` (envelope v2) com ``"schema": 3`` e o mapa
# assinado ``modules``. Os campos legados (tipo, vencimento, recursos, política) continuam valendo para
# o VYONIX DICOM Print e descrevem o **contrato** da licença. Cada módulo da plataforma é:
#   {"kind": "contract"} — segue o contrato (assinatura/permanente; renovações e autorizações de uso
#                          valem para ele), ou
#   {"kind": "demo", "days": N, "activate_by": data} — demonstração própria do módulo, contada a partir
#                          da aplicação da licença; deve ser aplicada até ``activate_by``.
# Todos levam ``grant_id`` (identifica o direito: prorrogação = mesmo grant_id com mais dias) e ``limits``.
# O módulo PRINT não aparece em ``modules``: ele é sempre derivado dos campos legados.
LICENSE_SCHEMA = 3
MODULE_CODES = ("core", "print", "edge", "cloud", "pacs", "viewer", "report", "ris", "patient", "notify", "flow",
                "connect", "deploy")
MODULE_LABELS = {"core": "VYONIX Core", "print": "VYONIX PRINT", "edge": "VYONIX EDGE", "cloud": "VYONIX CLOUD",
                 "pacs": "VYONIX PACS", "viewer": "VYONIX VIEWER", "report": "VYONIX REPORT", "ris": "VYONIX RIS",
                 "patient": "VYONIX PATIENT", "notify": "VYONIX NOTIFY", "flow": "VYONIX FLOW",
                 "connect": "VYONIX CONNECT", "deploy": "VYONIX DEPLOY"}
MODULE_KINDS = ("contract", "demo")
DEMO_DAY_CHOICES = (5, 15, 30)
DEMO_CUSTOM_MAX_DAYS = 90
MODULE_LIMITS = {"core": ("users", "sites"), "print": ("devices", "printers")}
_GRANT = re.compile(r"^G-[0-9A-F]{8,32}$")


def validate_modules(p: dict[str, Any]) -> list[str]:
    """Erros do mapa ``modules`` de uma licença v3 (vazio = válido). Licenças sem ``schema`` 3 não têm módulos."""
    if p.get("schema") in (None, 2):
        return [] if "modules" not in p else ["módulos em licença sem schema 3"]
    if p.get("schema") != LICENSE_SCHEMA:
        return [f"schema de licença desconhecido: {p.get('schema')}"]
    mods = p.get("modules")
    if not isinstance(mods, dict) or not mods:
        return ["licença v3 sem módulos"]
    errors: list[str] = []
    grants: set[str] = set()
    for code, m in mods.items():
        if code == "print":
            errors.append("o módulo PRINT é definido pelos campos da licença, não em modules")
            continue
        if code not in MODULE_CODES:
            errors.append(f"módulo desconhecido: {code}")
            continue
        if not isinstance(m, dict):
            errors.append(f"{code}: definição inválida")
            continue
        kind = m.get("kind")
        if kind not in MODULE_KINDS:
            errors.append(f"{code}: tipo inválido ({kind})")
        g = str(m.get("grant_id") or "")
        if not _GRANT.match(g):
            errors.append(f"{code}: grant_id inválido")
        elif g in grants:
            errors.append(f"{code}: grant_id repetido")
        grants.add(g)
        if kind == "demo":
            days = m.get("days")
            if not isinstance(days, int) or not 1 <= days <= DEMO_CUSTOM_MAX_DAYS:
                errors.append(f"{code}: demonstração deve ter de 1 a {DEMO_CUSTOM_MAX_DAYS} dias")
            try:
                parse_time(m["activate_by"])
            except (KeyError, ValueError, TypeError):
                errors.append(f"{code}: prazo de ativação ausente ou inválido")
        limits = m.get("limits") or {}
        if not isinstance(limits, dict):
            errors.append(f"{code}: limites inválidos")
        else:
            for k, v in limits.items():
                if k not in MODULE_LIMITS.get(code, ()):
                    errors.append(f"{code}: limite desconhecido ({k})")
                elif v is not None and (not isinstance(v, int) or not 1 <= v <= 100000):
                    errors.append(f"{code}: limite {k} inválido")
    if "core" not in mods:
        errors.append("licença da plataforma sem o módulo core")
    return errors


def license_modules(p: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Módulos efetivos de uma licença (v2 ou v3), já com o PRINT derivado dos campos legados.

    Licença v2 (anterior à plataforma): core e print seguem o contrato da licença — compatibilidade.
    """
    lid = str(p.get("license_id") or "")
    out: dict[str, dict[str, Any]] = {}
    if p.get("schema") == LICENSE_SCHEMA:
        for code, m in (p.get("modules") or {}).items():
            out[code] = {"kind": m["kind"], "grant_id": m["grant_id"], "limits": dict(m.get("limits") or {}),
                         **({"days": m["days"], "activate_by": m["activate_by"]} if m["kind"] == "demo" else {})}
    else:
        out["core"] = {"kind": "contract", "grant_id": "L-" + lid, "limits": {}}
    if p.get("features"):
        out["print"] = {"kind": "contract", "grant_id": "L-" + lid,
                        "limits": {"devices": p.get("max_devices"), "printers": p.get("max_printers")}}
    return out


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
