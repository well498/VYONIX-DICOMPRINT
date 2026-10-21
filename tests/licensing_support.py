"""Apoio aos testes de licenciamento: computador, TPM e relógio simulados + License Manager real.

O "computador" é um conjunto de identificadores de hardware; o "disco" do cliente é o conjunto de
locais do cofre (banco, ProgramData, registro), que sobrevive à desinstalação como no Windows.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed, decode_dss_signature

from app.database.connection import Database
from app.database.migrations import MIGRATIONS
from app.database.migrator import migrate
from app.database.repositories.events_repo import EventRepository
from app.licensing.demo import DemoService
from app.licensing.hardware import HardwareProvider
from app.licensing.installation import InstallationManager
from app.licensing.license import LicenseService
from app.licensing.time_integrity import SimulatedClock, TimeIntegrity, db_logger
from app.licensing.vault import KeySealer, MemoryBackend, Vault

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
PASS = "frase-senha-de-teste-123"


class FakeTpm:
    """TPM simulado: chave ECDSA P-256 não exportável (só assina), formato de blob do Windows CNG."""

    def __init__(self) -> None:
        self._key = ec.generate_private_key(ec.SECP256R1())
        n = self._key.public_key().public_numbers()
        self.blob = struct.pack("<II", 0x31534345, 32) + n.x.to_bytes(32, "big") + n.y.to_bytes(32, "big")
        self.present = True

    def info(self) -> dict:
        if not self.present:
            return {"available": False, "reason": "TPM removido"}
        return {"available": True, "alg": "ECDSA_P256", "pub": self.blob}

    def sign(self, digest32: bytes) -> bytes:
        if not self.present:
            raise RuntimeError("TPM indisponível")
        der = self._key.sign(digest32, ec.ECDSA(Prehashed(hashes.SHA256())))
        r, s = decode_dss_signature(der)
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")

    def provision(self) -> dict:
        return self.info()


@dataclass
class Computer:
    """Um computador: identificadores de hardware, TPM opcional, relógio e 'disco' (locais do cofre)."""

    uuid: str = "4C4C4544-0042-3510-8051-B7C04F4E3132"
    board: str = "Dell Inc.|0X3D6V|/7X1MZK2/CN129636A1002A/"
    system: str = "6f1d3c2a-9b8e-4f7a-a1c2-3d4e5f60718a"
    disk: str = "S4EWNX0R123456A"
    mac: list = field(default_factory=lambda: ["B8:CA:3A:11:22:33"])
    tpm: FakeTpm | None = None
    clock: SimulatedClock = field(default_factory=lambda: SimulatedClock(T0))
    db_backend: MemoryBackend = field(default_factory=lambda: MemoryBackend("banco de dados"))
    file_backend: MemoryBackend = field(default_factory=lambda: MemoryBackend("ProgramData"))
    reg_backend: MemoryBackend = field(default_factory=lambda: MemoryBackend("registro do Windows"))
    seal_key: bytes = b"k" * 32

    def raw(self):
        return ({"uuid": self.uuid, "board": self.board, "system": self.system, "disk": self.disk,
                 "mac": list(self.mac)}, {})

    def vault(self) -> Vault:
        return Vault([self.db_backend, self.file_backend, self.reg_backend], KeySealer(self.seal_key))


class Client:
    """Uma instalação do VYONIX DICOM Print em um computador."""

    def __init__(self, computer: Computer, folder: Path, public_keys: dict, *, enforced: bool = True) -> None:
        self.computer = computer
        folder.mkdir(parents=True, exist_ok=True)
        self.db = Database(folder / "vyonix.db")
        migrate(self.db, MIGRATIONS, backup_dir=folder / "bk")
        self.events = EventRepository(self.db)
        self.settings = {"site.name": "Clínica Teste", "system.installation_id": ""}
        self.reopen(public_keys, enforced=enforced)

    def reopen(self, public_keys: dict, *, enforced: bool = True) -> None:
        """Novo processo (fecha e abre o programa): memória limpa, mesmo disco."""
        c = self.computer
        vault = c.vault()
        self.vault = vault
        self.time = TimeIntegrity(vault, c.clock, log_event=db_logger(self.db, "teste"))
        self.svc = LicenseService(
            self.db, self.events, self.settings.get, vault=vault,
            hardware=HardwareProvider(c.tpm, collector=c.raw), tpm=c.tpm, installation=InstallationManager(vault),
            time_integrity=self.time, demo=DemoService(vault), public_keys=public_keys, enforced=enforced,
            settings_set=self.settings.__setitem__)

    def close(self) -> None:
        self.db.close()


def make_manager(folder: Path, clock=None):
    """License Manager real com administrador, chave gerada e desbloqueada, e um cliente cadastrado."""
    from license_manager.paths import LMPaths
    from license_manager.service import LicenseManager
    lm = LicenseManager(LMPaths(folder, "custom"), **({"clock": clock} if clock else {}))
    admin = lm.initialize("admin", "Administrador", "Senha-Forte-123")
    key = lm.generate_key(admin, "teste-01", PASS)
    lm.unlock_key(admin, PASS)
    cid = lm.save_customer(admin, {"name": "Clínica Teste Ltda", "document": "12.345.678/0001-90", "city": "Recife"})
    return lm, admin, {key["key_id"]: key["public_hex"]}, cid
