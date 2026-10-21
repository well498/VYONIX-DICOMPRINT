"""VYONIX Hardware ID — combinação normalizada de identificadores do computador.

Componentes (quando disponíveis): UUID SMBIOS, placa-mãe (fabricante + modelo + número de série),
identificador do Windows (``MachineGuid``), número de série do disco que contém o Windows, placas
de rede físicas (auxiliar) e a chave do TPM 2.0 criada pelo VYONIX (``tpm.py``).

Os valores originais **não saem do computador**: cada componente vira um resumo SHA-256 com
separação de domínio, e o Hardware ID exibido é o resumo da combinação. Esses resumos servem à
privacidade (LGPD: nenhum número de série legível na solicitação); a proteção contra cópia vem da
assinatura da licença, da prova de posse do TPM e das demais camadas — não do resumo em si.

Valores genéricos de fábrica ("To be filled by O.E.M.", UUID zerado etc.) são descartados, e um
componente ilegível fica ausente em vez de produzir um valor aleatório.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from vyonix_protocol.formats import HW_LABELS, HW_STRONG, hardware_id

log = logging.getLogger(__name__)

SALT = b"VYONIX/hardware-component/v2|"
JUNK = {
    "", "NONE", "NULL", "0", "00000000", "DEFAULT STRING", "TO BE FILLED BY O.E.M.", "TO BE FILLED BY OEM",
    "SYSTEM SERIAL NUMBER", "SYSTEM PRODUCT NAME", "BASE BOARD SERIAL NUMBER", "NOT APPLICABLE", "N/A", "NA",
    "INVALID", "NOT SPECIFIED", "OEM", "O.E.M.", "SERIAL", "123456789", "0123456789", "XXXXXXXXXX", "CHASSIS SERIAL",
    "00000000-0000-0000-0000-000000000000", "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF",
    "03000200-0400-0500-0006-000700080009",
}
_REFRESH_S = 6 * 3600


def normalize(value: Any) -> str | None:
    if value is None:
        return None
    v = re.sub(r"\s+", " ", str(value)).strip().strip(".").upper()
    if v in JUNK or set(v) <= {"0", "F", "-", " "} or len(v) < 3:
        return None
    return v


def component_digest(name: str, value: str) -> str:
    return hashlib.sha256(SALT + name.encode() + b"|" + value.encode("utf-8")).hexdigest()


@dataclass
class HardwareProfile:
    digests: dict[str, Any]                       # componente → resumo (mac → lista de resumos)
    available: dict[str, bool] = field(default_factory=dict)
    tpm: dict[str, Any] | None = None             # {"alg", "pub"(bytes)} quando há chave no TPM
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def hardware_id(self) -> str:
        return hardware_id(self.digests)

    def summary(self) -> list[tuple[str, str]]:
        out = []
        for c in (*HW_STRONG, "mac"):
            v = self.digests.get(c)
            if c == "mac":
                txt = f"{len(v)} placa(s)" if v else "não encontrado"
            else:
                txt = "considerado" if v else ("indisponível" + (f" ({self.errors[c]})" if c in self.errors else ""))
            out.append((HW_LABELS[c], txt))
        return out


def build_profile(raw: dict[str, Any], tpm: dict[str, Any] | None = None,
                  errors: dict[str, str] | None = None) -> HardwareProfile:
    """``raw``: valores originais por componente (``mac``: lista)."""
    digests: dict[str, Any] = {}
    for c in ("uuid", "board", "system", "disk"):
        v = normalize(raw.get(c))
        digests[c] = component_digest(c, v) if v else None
    macs = sorted({component_digest("mac", m) for m in (normalize(x) for x in raw.get("mac") or []) if m})
    digests["mac"] = macs
    if tpm and tpm.get("pub"):
        from vyonix_protocol.crypto import tpm_key_digest
        digests["tpm"] = tpm_key_digest(tpm["alg"], tpm["pub"])
    else:
        digests["tpm"] = None
    return HardwareProfile(digests=digests, available={c: bool(digests.get(c)) for c in (*HW_STRONG, "mac")},
                           tpm=tpm, errors=dict(errors or {}))


# ---------------------------------------------------------------------------- coleta (Windows)
def _machine_guid() -> str | None:
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                                 winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
            try:
                return str(winreg.QueryValueEx(key, "MachineGuid")[0])
            finally:
                winreg.CloseKey(key)
        except OSError:
            return None
    for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            text = Path(p).read_text().strip()
            if text:
                return text
        except OSError:
            continue
    return None


def _wmi_collect(errors: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    import pythoncom  # pywin32
    import win32com.client
    pythoncom.CoInitialize()
    try:
        svc = win32com.client.GetObject(r"winmgmts:{impersonationLevel=impersonate}!\\.\root\cimv2")

        def first(query: str):
            for item in svc.ExecQuery(query):
                return item
            return None
        try:
            p = first("SELECT UUID FROM Win32_ComputerSystemProduct")
            out["uuid"] = p.UUID if p else None
        except Exception as exc:  # noqa: BLE001
            errors["uuid"] = str(exc)[:80]
        try:
            b = first("SELECT Manufacturer, Product, SerialNumber FROM Win32_BaseBoard")
            serial = normalize(b.SerialNumber) if b else None
            out["board"] = f"{b.Manufacturer}|{b.Product}|{serial}" if b and serial else None
        except Exception as exc:  # noqa: BLE001
            errors["board"] = str(exc)[:80]
        try:
            drive = os.environ.get("SystemDrive", "C:")
            serial = None
            for part in svc.ExecQuery(f'ASSOCIATORS OF {{Win32_LogicalDisk.DeviceID="{drive}"}} '
                                      "WHERE AssocClass = Win32_LogicalDiskToPartition"):
                for disk in svc.ExecQuery(f'ASSOCIATORS OF {{Win32_DiskPartition.DeviceID="{part.DeviceID}"}} '
                                          "WHERE AssocClass = Win32_DiskDriveToDiskPartition"):
                    serial = normalize(disk.SerialNumber)
                    if serial:
                        serial = serial.replace(" ", "")
                        break
                if serial:
                    break
            out["disk"] = serial
        except Exception as exc:  # noqa: BLE001
            errors["disk"] = str(exc)[:80]
        try:
            macs, pci = [], []
            for n in svc.ExecQuery("SELECT MACAddress, PNPDeviceID FROM Win32_NetworkAdapter "
                                   "WHERE PhysicalAdapter = TRUE AND MACAddress IS NOT NULL"):
                mac = str(n.MACAddress or "").upper()
                pnp = str(n.PNPDeviceID or "").upper()
                if not re.fullmatch(r"([0-9A-F]{2}:){5}[0-9A-F]{2}", mac) or int(mac[:2], 16) & 0x02:
                    continue                       # endereço administrado localmente (virtual/aleatório)
                (pci if pnp.startswith("PCI\\") else macs).append(mac)
            out["mac"] = pci or macs
        except Exception as exc:  # noqa: BLE001
            errors["mac"] = str(exc)[:80]
    finally:
        pythoncom.CoUninitialize()
    return out


def _linux_collect() -> dict[str, Any]:
    def rd(p: str) -> str | None:
        try:
            return Path(p).read_text().strip() or None
        except OSError:
            return None
    out: dict[str, Any] = {"uuid": rd("/sys/class/dmi/id/product_uuid"),
                           "board": None, "disk": None, "mac": []}
    serial = rd("/sys/class/dmi/id/board_serial")
    if normalize(serial):
        out["board"] = f"{rd('/sys/class/dmi/id/board_vendor')}|{rd('/sys/class/dmi/id/board_name')}|{serial}"
    try:
        for dev in sorted(Path("/sys/class/net").iterdir()):
            if (dev / "device").exists():
                mac = rd(str(dev / "address"))
                if mac and not int(mac[:2], 16) & 0x02:
                    out["mac"].append(mac.upper())
    except OSError:
        pass
    return out


def collect_raw() -> tuple[dict[str, Any], dict[str, str]]:
    errors: dict[str, str] = {}
    raw: dict[str, Any] = {}
    if sys.platform == "win32":
        try:
            raw = _wmi_collect(errors)
        except Exception as exc:  # noqa: BLE001 - WMI indisponível: componentes ficam ausentes
            log.warning("WMI indisponível para o Hardware ID: %s", exc)
            for c in ("uuid", "board", "disk", "mac"):
                errors.setdefault(c, "WMI indisponível")
    else:
        raw = _linux_collect()
    raw["system"] = _machine_guid()
    return raw, errors


class HardwareProvider:
    """Coleta (com cache) o perfil de hardware. ``collector`` e ``tpm`` são injetáveis nos testes."""

    def __init__(self, tpm=None, collector: Callable[[], tuple[dict, dict]] = collect_raw) -> None:
        self.tpm = tpm
        self.collector = collector
        self._lock = threading.Lock()
        self._cache: tuple[float, HardwareProfile] | None = None

    def profile(self, refresh: bool = False) -> HardwareProfile:
        with self._lock:
            if self._cache and not refresh and time.monotonic() - self._cache[0] < _REFRESH_S:
                return self._cache[1]
        raw, errors = self.collector()
        tpm_info = None
        if self.tpm is not None:
            info = self.tpm.info()
            if info.get("available") and info.get("pub"):
                tpm_info = {"alg": info["alg"], "pub": info["pub"]}
            elif info.get("reason"):
                errors["tpm"] = info["reason"]
        prof = build_profile(raw, tpm_info, errors)
        with self._lock:
            self._cache = (time.monotonic(), prof)
        return prof
