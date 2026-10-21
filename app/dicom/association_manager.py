"""Política de associações DICOM (§4.1 itens 6, 9, 11 e 12; §16).

Uma associação é aceita quando existe uma **Regra DICOM** habilitada para a combinação porta de
entrada + *Called AE Title* (com o *Calling AE Title* e o IP dentro das restrições opcionais da
regra) — ver ``routing.py``. Destino desconhecido: rejeição 0x07; origem fora das restrições:
rejeição 0x03. Opcionalmente, o AE padrão do servidor na porta padrão aceita envios sem regra.

O limite de associações simultâneas é aplicado pelo próprio pynetdicom
(``maximum_associations``), que rejeita com "local limit exceeded".

Cada associação aceita recebe um :class:`AssociationContext`, usado para consolidar a
recepção em um único evento por associação (evita milhares de eventos em uma série de TC).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from app.devices.repository import Device, DeviceRepository

# Diagnósticos do A-ASSOCIATE-RJ (fonte 0x01, DUL service user)
DIAG_CALLING_AE = 0x03
DIAG_CALLED_AE = 0x07

# Autoteste do próprio VYONIX (botão "Testar" na tela do servidor): aceito só a partir do
# próprio computador (loopback), nunca pela rede.
SELFTEST_AE = "VYONIX_TEST"
LOOPBACK = {"127.0.0.1", "::1"}


@dataclass(frozen=True)
class Decision:
    accepted: bool
    reason: str
    device_id: int | None = None
    device_name: str | None = None
    diagnostic: int = 0


class AssociationPolicy:
    """Aceita/recusa associações escolhendo a Regra DICOM (``app/dicom/routing.py``)."""

    def __init__(self, devices: DeviceRepository) -> None:
        self.devices = devices

    def evaluate(self, *, calling_ae: str, called_ae: str, address: str, local_ae: str,
                 accept_unknown: bool, local_addresses: frozenset[str] = frozenset(), port: int | None = None,
                 default_port: int | None = None, service: str = "store") -> Decision:
        from app.dicom import routing
        calling = (calling_ae or "").strip()
        called = (called_ae or "").strip()
        port = int(port or default_port or 0)
        default_port = int(default_port or port)
        local = {"127.0.0.1", "::1", *local_addresses}
        try:
            from app.utils.net import all_local_addresses
            local |= set(all_local_addresses())
        except Exception:  # noqa: BLE001
            pass
        res = routing.select(self.devices.routes(service), port=port, default_port=default_port, called_ae=called,
                             calling_ae=calling, address=address)
        if calling == SELFTEST_AE and address in local:
            # Autoteste do próprio computador (tela "Configurar destino"): valida porta + destino.
            if res.rule is not None or called == local_ae.strip():
                return Decision(True, "Autoteste local" + (f" ({res.reason})" if res.rule else ""),
                                res.rule.id if res.rule else None, res.rule.name if res.rule else None)
            return Decision(False, res.reason, diagnostic=res.diagnostic)
        if res.accepted:
            return Decision(True, f"Associação aceita pela {res.reason}", res.rule.id, res.rule.name)
        if service == "print" and res.rule is None and res.diagnostic == routing.DIAG_CALLED_AE \
                and called == local_ae.strip() and port == default_port:
            # Compatibilidade 1.0.0: impressão DICOM no AE padrão de impressão, origem identificada pela
            # regra de recepção com o mesmo Calling AE Title (e IP, se restrito).
            from app.security.validators import ip_allowed
            legacy = [r for r in self.devices.routes("store")
                      if r.calling_restriction == calling and ip_allowed(address, r.ip_address)]
            if len(legacy) == 1 and legacy[0].authorized:
                return Decision(True, f"Impressão DICOM no AE padrão; origem pela regra “{legacy[0].name}”",
                                legacy[0].id, legacy[0].name)
        if res.rule is None and res.diagnostic == routing.DIAG_CALLED_AE and called == local_ae.strip() \
                and port == default_port and accept_unknown:
            return Decision(True, "Destino padrão do servidor sem regra (configurações globais)")
        return Decision(False, res.reason[:1].upper() + res.reason[1:], res.rule.id if res.rule else None,
                        res.rule.name if res.rule else None, diagnostic=res.diagnostic)


@dataclass
class AssociationContext:
    key: int
    calling_ae: str
    called_ae: str
    address: str
    port: int
    device_id: int | None
    device_name: str | None
    started: float = field(default_factory=time.monotonic)
    received: int = 0
    duplicates: int = 0
    failures: int = 0
    bytes: int = 0
    echoes: int = 0
    modalities: set[str] = field(default_factory=set)

    def as_dict(self) -> dict:
        return {"calling_ae": self.calling_ae, "address": self.address, "device": self.device_name,
                "received": self.received, "duplicates": self.duplicates, "failures": self.failures,
                "seconds": round(time.monotonic() - self.started, 1)}


class AssociationRegistry:
    """Associações ativas, seguras para acesso concorrente."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[int, AssociationContext] = {}

    def add(self, ctx: AssociationContext) -> None:
        with self._lock:
            self._items[ctx.key] = ctx

    def get(self, key: int) -> AssociationContext | None:
        with self._lock:
            return self._items.get(key)

    def pop(self, key: int) -> AssociationContext | None:
        with self._lock:
            return self._items.pop(key, None)

    def update(self, key: int, fn: Callable[[AssociationContext], None]) -> None:
        with self._lock:
            ctx = self._items.get(key)
            if ctx is not None:
                fn(ctx)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [c.as_dict() for c in self._items.values()]

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
