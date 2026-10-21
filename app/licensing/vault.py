"""Cofre de estado do licenciamento (camada 5 — integridade de estado).

Cada registro (instalação, demonstração, horário, ativações, revogações…) é gravado **selado**
(HMAC-SHA256) em vários locais independentes:

* banco de dados do VYONIX (tabela ``licensing_vault``);
* pasta ``%ProgramData%\\VYONIX\\Licensing`` (fora da pasta de dados que a desinstalação pode apagar);
* registro do Windows ``HKLM\\SOFTWARE\\VYONIX\\DICOM Print\\State`` (gravado pelo instalador e pelo
  serviço; a interface, como usuário comum, só lê).

A chave do selo é aleatória e protegida pelo DPAPI do Windows no escopo da máquina: um registro
copiado de outro computador não confere. Um registro **presente com selo inválido** é tratado
como adulteração (não como ausência); registros ausentes em um local são restaurados a partir dos
demais. Limites (documentados): um administrador local que apague todos os locais ao mesmo tempo,
ou a restauração completa de uma imagem de disco, retornam o estado anterior.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

from vyonix_protocol.codec import canonical

log = logging.getLogger(__name__)

REG_PATH = r"SOFTWARE\VYONIX\DICOM Print"


# ---------------------------------------------------------------------------- selo
class Sealer(Protocol):
    def mac(self, data: bytes) -> str: ...


class KeySealer:
    def __init__(self, key: bytes) -> None:
        self.key = key

    def mac(self, data: bytes) -> str:
        return hmac.new(self.key, data, hashlib.sha256).hexdigest()


def machine_sealer(state_dir: Path, *, use_registry: bool = True) -> KeySealer:
    """Chave do selo: 32 bytes aleatórios, protegidos pelo DPAPI da máquina (Windows)."""
    path = state_dir / "seal.key"
    if sys.platform != "win32":
        # Desenvolvimento/testes fora do Windows: arquivo local sem DPAPI (não é usado em produção).
        try:
            return KeySealer(path.read_bytes()[:32])
        except OSError:
            key = secrets.token_bytes(32)
            state_dir.mkdir(parents=True, exist_ok=True)
            path.write_bytes(key)
            return KeySealer(key)
    import win32crypt
    CRYPTPROTECT_LOCAL_MACHINE = 0x4
    for blob in _seal_blobs(path, use_registry):
        try:
            _desc, key = win32crypt.CryptUnprotectData(blob, None, None, None, 0)
            if len(key) == 32:
                return KeySealer(bytes(key))
        except Exception:  # noqa: BLE001 - blob de outro computador ou corrompido
            continue
    key = secrets.token_bytes(32)
    blob = win32crypt.CryptProtectData(key, "VYONIX Licensing", None, None, None, CRYPTPROTECT_LOCAL_MACHINE)
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
    except OSError as exc:
        log.warning("Não foi possível gravar a chave do selo: %s", exc)
    if use_registry:
        RegistryBackend().put_bytes("SealKey", blob)
    return KeySealer(key)


def _seal_blobs(path: Path, use_registry: bool) -> list[bytes]:
    out = []
    try:
        out.append(path.read_bytes())
    except OSError:
        pass
    b = RegistryBackend().get_bytes("SealKey") if use_registry else None
    if b:
        out.append(b)
    return out


# ---------------------------------------------------------------------------- locais
class Backend(Protocol):
    label: str

    def get(self, name: str) -> str | None: ...
    def put(self, name: str, text: str) -> bool: ...
    def delete(self, name: str) -> None: ...


class MemoryBackend:
    def __init__(self, label: str = "memória") -> None:
        self.label = label
        self.data: dict[str, str] = {}
        self.readonly = False

    def get(self, name: str) -> str | None:
        return self.data.get(name)

    def put(self, name: str, text: str) -> bool:
        if self.readonly:
            return False
        self.data[name] = text
        return True

    def delete(self, name: str) -> None:
        if not self.readonly:
            self.data.pop(name, None)


class FileBackend:
    def __init__(self, folder: Path, label: str = "ProgramData") -> None:
        self.folder = Path(folder)
        self.label = label

    def _p(self, name: str) -> Path:
        return self.folder / f"{name}.vxs"

    def get(self, name: str) -> str | None:
        try:
            return self._p(name).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def put(self, name: str, text: str) -> bool:
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            tmp = self._p(name).with_suffix(".tmp")
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, self._p(name))
            return True
        except OSError:
            return False

    def delete(self, name: str) -> None:
        try:
            self._p(name).unlink()
        except OSError:
            pass


class DbBackend:
    label = "banco de dados"

    def __init__(self, db) -> None:
        self.db = db

    def get(self, name: str) -> str | None:
        try:
            r = self.db.connection().execute("SELECT value FROM licensing_vault WHERE name = ?", (name,)).fetchone()
        except Exception:  # noqa: BLE001 - tabela ainda inexistente (antes da migração)
            return None
        return r["value"] if r else None

    def put(self, name: str, text: str) -> bool:
        from app.utils.timeutil import utc_now_iso
        try:
            self.db.connection().execute(
                """INSERT INTO licensing_vault(name, value, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
                (name, text, utc_now_iso()))
            return True
        except Exception:  # noqa: BLE001
            return False

    def delete(self, name: str) -> None:
        try:
            self.db.connection().execute("DELETE FROM licensing_vault WHERE name = ?", (name,))
        except Exception:  # noqa: BLE001
            pass


class RegistryBackend:
    label = "registro do Windows"

    def __init__(self, subkey: str = REG_PATH + r"\State") -> None:
        self.subkey = subkey

    def _key(self, write: bool):
        import winreg
        access = (winreg.KEY_READ | winreg.KEY_WRITE) if write else winreg.KEY_READ
        access |= winreg.KEY_WOW64_64KEY
        if write:
            return winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, self.subkey, 0, access)
        return winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self.subkey, 0, access)

    def get(self, name: str) -> str | None:
        if sys.platform != "win32":
            return None
        import winreg
        try:
            with self._key(False) as k:
                return str(winreg.QueryValueEx(k, name)[0])
        except OSError:
            return None

    def put(self, name: str, text: str) -> bool:
        if sys.platform != "win32":
            return False
        import winreg
        try:
            with self._key(True) as k:
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, text)
            return True
        except OSError:
            return False                            # usuário comum: somente leitura

    def delete(self, name: str) -> None:
        if sys.platform != "win32":
            return
        import winreg
        try:
            with self._key(True) as k:
                winreg.DeleteValue(k, name)
        except OSError:
            pass

    def get_bytes(self, name: str) -> bytes | None:
        if sys.platform != "win32":
            return None
        import winreg
        try:
            with self._key(False) as k:
                v = winreg.QueryValueEx(k, name)[0]
                return bytes(v) if isinstance(v, (bytes, bytearray)) else None
        except OSError:
            return None

    def put_bytes(self, name: str, data: bytes) -> bool:
        if sys.platform != "win32":
            return False
        import winreg
        try:
            with self._key(True) as k:
                winreg.SetValueEx(k, name, 0, winreg.REG_BINARY, data)
            return True
        except OSError:
            return False


# ---------------------------------------------------------------------------- cofre
@dataclass
class Copy:
    backend: str
    record: dict[str, Any] | None
    valid: bool


@dataclass
class VaultRead:
    name: str
    copies: list[Copy] = field(default_factory=list)

    @property
    def valid(self) -> list[dict[str, Any]]:
        return [c.record for c in self.copies if c.valid and c.record is not None]

    @property
    def tampered(self) -> list[str]:
        return [c.backend for c in self.copies if not c.valid]

    @property
    def present(self) -> bool:
        return bool(self.copies)


class Vault:
    def __init__(self, backends: Iterable[Backend], sealer: Sealer) -> None:
        self.backends = list(backends)
        self.sealer = sealer
        self._lock = threading.RLock()

    def _seal(self, name: str, record: dict[str, Any]) -> str:
        return json.dumps({"r": record, "s": self.sealer.mac(canonical({"n": name, "r": record}))},
                          ensure_ascii=False, sort_keys=True)

    def _open(self, name: str, text: str) -> tuple[dict[str, Any] | None, bool]:
        try:
            doc = json.loads(text)
            rec, seal = doc["r"], str(doc["s"])
        except Exception:  # noqa: BLE001
            return None, False
        ok = hmac.compare_digest(seal, self.sealer.mac(canonical({"n": name, "r": rec})))
        return (rec if isinstance(rec, dict) else None), ok and isinstance(rec, dict)

    def read(self, name: str) -> VaultRead:
        out = VaultRead(name)
        with self._lock:
            for b in self.backends:
                text = b.get(name)
                if text is None:
                    continue
                rec, ok = self._open(name, text)
                out.copies.append(Copy(b.label, rec, ok))
        return out

    def best(self, name: str, pick: Callable[[list[dict[str, Any]]], dict[str, Any]] | None = None,
             *, repair: bool = True) -> tuple[dict[str, Any] | None, VaultRead]:
        """Registro escolhido entre as cópias válidas (``pick``; padrão: maior ``seq``).

        Com ``repair``, locais sem cópia recebem o registro escolhido (cópias adulteradas não são
        sobrescritas: ficam como evidência até a revalidação administrativa)."""
        rd = self.read(name)
        valid = rd.valid
        if not valid:
            return None, rd
        rec = (pick or _max_seq)(valid)
        if repair:
            have = {c.backend for c in rd.copies}
            text = self._seal(name, rec)
            for b in self.backends:
                if b.label not in have:
                    b.put(name, text)
        return rec, rd

    def write(self, name: str, record: dict[str, Any], *, overwrite_tampered: bool = True) -> int:
        record = dict(record)
        record["seq"] = int(record.get("seq", 0)) + 1
        text = self._seal(name, record)
        n = 0
        with self._lock:
            for b in self.backends:
                if not overwrite_tampered:
                    cur = b.get(name)
                    if cur is not None and not self._open(name, cur)[1]:
                        continue
                n += bool(b.put(name, text))
        return n

    def delete(self, name: str) -> None:
        with self._lock:
            for b in self.backends:
                b.delete(name)


def _max_seq(recs: list[dict[str, Any]]) -> dict[str, Any]:
    return max(recs, key=lambda r: int(r.get("seq", 0)))
