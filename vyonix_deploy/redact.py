"""Filtro de redação: nada de senhas, tokens, chaves privadas ou dados de pacientes em relatórios e
manifestos. Roda antes da geração; ``forbidden_hits`` é usado pelos testes e pela própria geração
(que recusa gravar se algo escapar)."""

from __future__ import annotations

import re
from typing import Any

SENSITIVE_KEY = re.compile(r"(pass(word)?|senha|secret|token|private|pwd|credential|api[_-]?key|cookie|csrf|"
                           r"pfx_password|admin_password)", re.I)
PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[chave privada removida]"),
    (re.compile(r"(postgres(?:ql)?(?:\+\w+)?://[^:/\s@]+):[^@\s]+@"), r"\1:***@"),
    (re.compile(r"\b(dpapi|plain):[A-Za-z0-9+/=]{16,}"), r"\1:***"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "[token removido]"),
    (re.compile(r"(?i)(password|senha|pwd)\s*[=:]\s*\S+"), r"\1=***"),
]
FORBIDDEN = [re.compile(r"PRIVATE KEY-----"), re.compile(r"postgres(?:ql)?://[^:/\s@]+:(?!\*\*\*@)[^@\s]+@"),
             re.compile(r"\b(dpapi|plain):[A-Za-z0-9+/=]{16,}"), re.compile(r"(?i)(password|senha)\s*[=:]\s*(?!\*\*\*)\S+")]


def text(s: str, extra_secrets: list[str] | None = None) -> str:
    for rx, rep in PATTERNS:
        s = rx.sub(rep, s)
    for sec in extra_secrets or []:
        if sec and len(sec) >= 6:
            s = s.replace(sec, "***")
    return s


def value(v: Any, extra_secrets: list[str] | None = None, key: str = "") -> Any:
    if key and SENSITIVE_KEY.search(key) and v not in (None, "", False, [], {}):
        return "***"
    if isinstance(v, dict):
        return {k: value(x, extra_secrets, str(k)) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [value(x, extra_secrets) for x in v]
    if isinstance(v, str):
        return text(v, extra_secrets)
    return v


def forbidden_hits(s: str, secrets: list[str] | None = None) -> list[str]:
    hits = [rx.pattern for rx in FORBIDDEN if rx.search(s)]
    hits += ["valor de segredo" for sec in secrets or [] if sec and len(sec) >= 6 and sec in s]
    return hits
