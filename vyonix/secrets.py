"""Segredos locais do CORE (senhas do banco, chave de cifra de fatores MFA).

* Windows: cada segredo é protegido com DPAPI no escopo da máquina (``CryptProtectData`` com
  ``CRYPTPROTECT_LOCAL_MACHINE``), o mesmo mecanismo do cofre de licenciamento do DICOM Print.
* Outros sistemas: arquivo com permissão 0600 do usuário do serviço.

Nenhum segredo é gravado em ``config.json``: o arquivo só contém referências ``{secret:nome}``.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import sys
from pathlib import Path


def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))
    inp, out = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), Blob()
    flags = 0x4 | 0x1                      # CRYPTPROTECT_LOCAL_MACHINE | CRYPTPROTECT_UI_FORBIDDEN
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(inp), None, None, None, None, flags, ctypes.byref(out))
    if not ok:
        raise OSError("DPAPI recusou a operação.")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


class SecretStore:
    def __init__(self, data_dir: Path) -> None:
        self.file = Path(data_dir) / "secrets.json"

    def _load(self) -> dict[str, str]:
        if not self.file.exists():
            return {}
        return json.loads(self.file.read_text(encoding="utf-8"))

    def _save(self, data: dict[str, str]) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        if sys.platform != "win32":
            os.chmod(tmp, 0o600)
        os.replace(tmp, self.file)

    def put(self, name: str, value: bytes | str) -> None:
        raw = value.encode() if isinstance(value, str) else value
        data = self._load()
        if sys.platform == "win32":
            data[name] = "dpapi:" + base64.b64encode(_dpapi(raw, True)).decode()
        else:
            data[name] = "plain:" + base64.b64encode(raw).decode()
        self._save(data)

    def get(self, name: str) -> bytes | None:
        v = self._load().get(name)
        if v is None:
            return None
        kind, _, b = v.partition(":")
        raw = base64.b64decode(b)
        return _dpapi(raw, False) if kind == "dpapi" else raw

    def get_or_create(self, name: str, size: int = 32) -> bytes:
        v = self.get(name)
        if v is None:
            v = secrets.token_bytes(size)
            self.put(name, v)
        return v

    def get_or_create_text(self, name: str) -> str:
        """Senha aleatória (texto seguro para URL), criada na primeira vez."""
        v = self.get(name)
        if v is None:
            v = secrets.token_urlsafe(24).encode()
            self.put(name, v)
        return v.decode()

    def delete(self, name: str) -> None:
        data = self._load()
        if data.pop(name, None) is not None:
            self._save(data)

    def expand(self, text: str) -> str:
        import re

        def sub(m):
            v = self.get(m.group(1))
            if v is None:
                raise KeyError(f"Segredo ausente: {m.group(1)}")
            return v.decode()
        return re.sub(r"\{secret:([A-Za-z0-9_.-]+)\}", sub, text)
