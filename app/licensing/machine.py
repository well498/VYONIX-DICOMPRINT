"""Identificação do computador para a licença, sem expor identificadores de hardware.

O ``machine_id`` é um hash SHA-256 (truncado) do ``MachineGuid`` do Windows — criado na instalação
do Windows e estável entre reinicializações e atualizações — combinado com um sal fixo do produto.
Nenhum número de série, MAC ou nome de usuário é coletado. Trocar de computador ou reinstalar o
Windows muda o ``machine_id`` e exige reemitir a licença.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

SALT = b"VYONIX-DICOM-PRINT/machine/v1"


def _raw_machine_guid() -> str | None:
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


def machine_id() -> str:
    raw = _raw_machine_guid() or "desconhecido"
    return hashlib.sha256(SALT + raw.strip().lower().encode("utf-8")).hexdigest()[:32]
