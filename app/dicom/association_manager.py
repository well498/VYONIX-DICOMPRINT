"""Política de associações DICOM (§4.1 itens 6, 9, 11 e 12; §16).

Uma associação é aceita somente quando:

1. o *Called AE Title* é o AE Title local configurado (senão: rejeição 0x07);
2. o *Calling AE Title* pertence a um equipamento ativo **e autorizado** — ou a opção
   "aceitar equipamentos não cadastrados" está ligada (senão: rejeição 0x03);
3. o equipamento tem IP cadastrado e a conexão vem desse IP (senão: rejeição 0x03).

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
    def __init__(self, devices: DeviceRepository) -> None:
        self.devices = devices

    def evaluate(self, *, calling_ae: str, called_ae: str, address: str, local_ae: str,
                 accept_unknown: bool, local_addresses: frozenset[str] = frozenset()) -> Decision:
        calling = (calling_ae or "").strip()
        called = (called_ae or "").strip()
        if called != local_ae.strip():
            return Decision(False, f"Called AE '{called}' diferente do AE local '{local_ae}'",
                            diagnostic=DIAG_CALLED_AE)
        if calling == SELFTEST_AE and (address in LOOPBACK or address in local_addresses):
            return Decision(True, "Autoteste local")
        device, conflict = self.devices.match(calling, address)
        if conflict:
            return Decision(False, conflict.capitalize(), diagnostic=DIAG_CALLING_AE)
        if device is None:
            if accept_unknown:
                return Decision(True, "Equipamento não cadastrado aceito (opção habilitada)")
            return Decision(False, f"AE '{calling}' não cadastrado", diagnostic=DIAG_CALLING_AE)
        if not device.authorized:
            return Decision(False, f"Equipamento \"{device.name}\" bloqueado", device.id, device.name,
                            diagnostic=DIAG_CALLING_AE)
        if device.ip_address and device.ip_address != address:
            return Decision(False, f"IP de origem {address} diferente do cadastrado "
                                   f"({device.ip_address}) para \"{device.name}\"",
                            device.id, device.name, diagnostic=DIAG_CALLING_AE)
        return Decision(True, f"Equipamento \"{device.name}\" autorizado", device.id, device.name)


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
