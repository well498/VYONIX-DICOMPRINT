"""Validadores de entrada usados pelas configurações e, futuramente, pelo cadastro de equipamentos."""

from __future__ import annotations

import ipaddress
from typing import Any

from app.core.errors import ValidationError

AE_TITLE_MAX = 16
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
THEMES = ("system", "light", "dark")


def validate_ae_title(value: Any) -> str:
    """Valida um AE Title segundo a VR AE (DICOM PS3.5).

    * até 16 caracteres;
    * repertório padrão (ASCII imprimível), sem barra invertida nem caracteres de controle;
    * espaços iniciais e finais não são significativos e são removidos;
    * não pode ser vazio ou composto apenas por espaços.
    """
    if not isinstance(value, str):
        raise ValidationError("AE Title deve ser texto.")
    stripped = value.strip(" ")
    if not stripped:
        raise ValidationError("AE Title não pode ser vazio.")
    if len(stripped) > AE_TITLE_MAX:
        raise ValidationError(f"AE Title deve ter no máximo {AE_TITLE_MAX} caracteres.")
    for ch in stripped:
        code = ord(ch)
        if ch == "\\":
            raise ValidationError("AE Title não pode conter barra invertida (\\).")
        if code < 0x20 or code > 0x7E:
            raise ValidationError("AE Title aceita apenas caracteres ASCII imprimíveis.")
    return stripped


def validate_port(value: Any) -> int:
    port = _as_int(value, "Porta")
    if not 1 <= port <= 65535:
        raise ValidationError("Porta deve estar entre 1 e 65535.")
    return port


def port_warnings(port: int) -> list[str]:
    warnings: list[str] = []
    if port < 1024:
        warnings.append(
            "Portas abaixo de 1024 (ex.: 104) podem exigir privilégios administrativos "
            "e regras específicas de firewall."
        )
    return warnings


def validate_bind_address(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("Endereço IP inválido.")
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError as exc:
        raise ValidationError(f"Endereço IP inválido: {value!r}.") from exc


def validate_log_level(value: Any) -> str:
    if not isinstance(value, str) or value.upper() not in LOG_LEVELS:
        raise ValidationError(f"Nível de log deve ser um de: {', '.join(LOG_LEVELS)}.")
    return value.upper()


def validate_theme(value: Any) -> str:
    if value not in THEMES:
        raise ValidationError(f"Tema deve ser um de: {', '.join(THEMES)}.")
    return value


def int_range(minimum: int, maximum: int, label: str):
    def _validator(value: Any) -> int:
        number = _as_int(value, label)
        if not minimum <= number <= maximum:
            raise ValidationError(f"{label} deve estar entre {minimum} e {maximum}.")
        return number
    return _validator


def free_text(max_len: int, label: str):
    def _validator(value: Any) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValidationError(f"{label} deve ser texto.")
        if len(value) > max_len:
            raise ValidationError(f"{label} deve ter no máximo {max_len} caracteres.")
        if any(ord(c) < 0x20 for c in value):
            raise ValidationError(f"{label} contém caracteres de controle.")
        return value.strip()
    return _validator


def _as_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ValidationError(f"{label} deve ser um número inteiro.")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    raise ValidationError(f"{label} deve ser um número inteiro.")


def validate_ip_restriction(value: Any) -> str:
    """Restrição opcional de origem: IPs e/ou faixas CIDR separados por vírgula (ex.: 192.168.1.0/24)."""
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("Restrição de IP vazia.")
    items = []
    for part in value.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            net = ipaddress.ip_network(part, strict=False)
        except ValueError as exc:
            raise ValidationError(f"IP ou faixa inválida: {part!r} (use 192.168.1.20 ou 192.168.1.0/24).") from exc
        items.append(str(net.network_address) if net.num_addresses == 1 else str(net))
    if not items:
        raise ValidationError("Restrição de IP vazia.")
    return ", ".join(items)


def ip_allowed(address: str | None, restriction: str | None) -> bool:
    if not restriction:
        return True
    try:
        ip = ipaddress.ip_address((address or "").split("%")[0])
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    for part in restriction.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if ip in ipaddress.ip_network(part, strict=False):
                return True
        except ValueError:
            continue
    return False
