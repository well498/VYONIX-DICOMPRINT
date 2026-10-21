"""Camada opcional de cobrança: interface comum dos provedores (Banco Inter e futuros).

O VYONIX DICOM Print instalado na clínica **não** usa esta camada nem guarda credenciais bancárias:
ela roda no VYONIX License Server (ou, para testes de homologação, no License Manager).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

# Situação normalizada de uma cobrança. Somente PAID confirma pagamento.
PAID = "paid"
OPEN = "issued"
OVERDUE = "overdue"
CANCELLED = "cancelled"
EXPIRED = "expired"
MANUAL_CHECK = "manual_check"       # baixa manual informada no banco: exige conferência do financeiro


class BillingError(Exception):
    """Falha de comunicação ou resposta inesperada do provedor."""


@dataclass
class ChargeRequest:
    our_number: str                 # "seu número": identificador da cobrança no VYONIX
    amount_cents: int
    due_date: str                   # AAAA-MM-DD
    payer_name: str
    payer_document: str             # CPF/CNPJ (somente dígitos)
    payer_email: str | None = None
    payer_address: dict[str, str] = field(default_factory=dict)
    message: str | None = None


@dataclass
class ChargeStatus:
    provider_ref: str
    status: str                     # PAID / OPEN / OVERDUE / CANCELLED / EXPIRED / MANUAL_CHECK
    provider_status: str
    paid_cents: int | None = None
    paid_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class WebhookNotice:
    """Aviso recebido do banco. Não é prova de pagamento: identifica o que consultar."""
    provider_ref: str
    event_key: str                  # identificador para descartar repetições
    claimed_status: str


class BillingProvider(Protocol):
    name: str

    def create_charge(self, req: ChargeRequest) -> str: ...

    def charge_status(self, provider_ref: str) -> ChargeStatus: ...

    def parse_webhook(self, body: bytes) -> list[WebhookNotice]: ...
