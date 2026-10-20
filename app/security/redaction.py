"""Minimização de dados de paciente em logs, eventos e exportações (LGPD).

Política: código do VYONIX não deve registrar dados demográficos. Esta camada é a
rede de proteção para quando isso acontecer por engano (ex.: ``str(dataset)`` do
pydicom em uma mensagem de erro, ou um dicionário de atributos em ``extra``).
"""

from __future__ import annotations

import re
from typing import Any

MASK = "***"

# Chaves comparadas após normalização (minúsculas, sem "_", "-", espaços ou "'").
_SENSITIVE_KEYS = {
    "patientname", "patientid", "patientbirthdate", "patientbirthtime", "patientsex",
    "patientage", "patientaddress", "patienttelephonenumbers", "patientmothersbirthname",
    "otherpatientids", "otherpatientnames", "patientweight", "patientsize",
    "accessionnumber", "referringphysicianname", "performingphysicianname",
    "requestingphysician", "institutionaladdress", "cpf", "rg", "cns", "birthdate",
    "nome", "nomepaciente", "datanascimento",
}

_KEYWORDS = (
    "PatientName|PatientID|PatientBirthDate|PatientBirthTime|PatientSex|PatientAge|"
    "PatientAddress|OtherPatientIDs|OtherPatientNames|AccessionNumber|"
    "ReferringPhysicianName|PerformingPhysicianName|Patient's Name|Patient ID|"
    "Patient's Birth Date|Patient's Sex|Accession Number|Referring Physician's Name"
)

# Ex.: "PatientName=DOE^JOHN", "PatientID: 12345", "AccessionNumber='A1'"
_KEYWORD_RE = re.compile(
    rf"(?P<k>\b(?:{_KEYWORDS}))(?P<sep>\s*[=:]\s*)(?P<v>\"[^\"]*\"|'[^']*'|[^,;\s\]\)\}}]+)",
    re.IGNORECASE,
)

# Linhas no formato de ``str(dataset)`` do pydicom:
# "(0010,0010) Patient's Name                      PN: 'DOE^JOHN'"
_TAG_LINE_RE = re.compile(
    r"(?P<prefix>\((?:0010|0008),\s?(?P<elem>[0-9A-Fa-f]{4})\)[^\n:]*:\s*)(?P<v>[^\n]+)"
)
_SENSITIVE_0008 = {"0050", "0090", "1050", "1060", "0081"}


def _normalize(key: str) -> str:
    return re.sub(r"[\s_\-']", "", key).lower()


def is_sensitive_key(key: str) -> bool:
    return _normalize(str(key)) in _SENSITIVE_KEYS


def redact_text(text: str) -> str:
    if not text:
        return text

    def _tag(m: re.Match[str]) -> str:
        whole = m.group(0)
        group = whole[1:5]
        if group == "0010" or m.group("elem").upper() in _SENSITIVE_0008:
            return m.group("prefix") + MASK
        return whole

    text = _TAG_LINE_RE.sub(_tag, text)
    return _KEYWORD_RE.sub(lambda m: f"{m.group('k')}{m.group('sep')}{MASK}", text)


def redact(value: Any) -> Any:
    """Redige recursivamente dicionários, listas e textos."""
    if isinstance(value, dict):
        return {k: (MASK if is_sensitive_key(k) else redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(redact(v) for v in value)
    if isinstance(value, str):
        return redact_text(value)
    return value
