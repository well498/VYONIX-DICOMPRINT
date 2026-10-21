"""Backup protegido do License Manager: banco inteiro cifrado (AES-256-GCM, chave derivada da
frase-senha por scrypt — primitivas da biblioteca ``cryptography``).

Formato ``.vylmbak``: ``b"VYXLMBK1"`` + tamanho (4 bytes) + cabeçalho JSON + texto cifrado. O
cabeçalho (sal, parâmetros, data, versão do esquema) é autenticado como dado associado.
"""

from __future__ import annotations

import json
import os
import sqlite3
import struct
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"VYXLMBK1"
N = 2 ** 15


class BackupError(Exception):
    pass


def _key(passphrase: str, salt: bytes, n: int) -> bytes:
    return Scrypt(salt=salt, length=32, n=n, r=8, p=1).derive(passphrase.encode("utf-8"))


def snapshot(db_file: Path) -> bytes:
    """Cópia consistente do banco (API de backup do SQLite)."""
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        src = sqlite3.connect(db_file)
        dst = sqlite3.connect(tmp)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        return Path(tmp).read_bytes()
    finally:
        os.unlink(tmp)


def encrypt(data: bytes, passphrase: str, meta: dict) -> bytes:
    if len(passphrase) < 10:
        raise BackupError("A frase-senha do backup deve ter pelo menos 10 caracteres.")
    salt, nonce = os.urandom(16), os.urandom(12)
    header = dict(meta, kdf="scrypt", n=N, salt=salt.hex(), nonce=nonce.hex(),
                  created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    hb = json.dumps(header, sort_keys=True).encode()
    ct = AESGCM(_key(passphrase, salt, N)).encrypt(nonce, data, hb)
    return MAGIC + struct.pack(">I", len(hb)) + hb + ct


def read_header(blob: bytes) -> dict:
    if not blob.startswith(MAGIC):
        raise BackupError("O arquivo não é um backup do VYONIX License Manager.")
    (n,) = struct.unpack(">I", blob[8:12])
    return json.loads(blob[12:12 + n])


def decrypt(blob: bytes, passphrase: str) -> tuple[dict, bytes]:
    header = read_header(blob)
    (n,) = struct.unpack(">I", blob[8:12])
    hb = blob[12:12 + n]
    try:
        data = AESGCM(_key(passphrase, bytes.fromhex(header["salt"]), int(header["n"]))).decrypt(
            bytes.fromhex(header["nonce"]), blob[12 + n:], hb)
    except InvalidTag as exc:
        raise BackupError("Frase-senha incorreta ou backup alterado/corrompido.") from exc
    return header, data


def verify_sqlite(data: bytes) -> int:
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        Path(tmp).write_bytes(data)
        c = sqlite3.connect(tmp)
        try:
            if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupError("O banco dentro do backup está danificado.")
            return int(c.execute("PRAGMA user_version").fetchone()[0])
        finally:
            c.close()
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"O conteúdo do backup não é um banco válido: {exc}") from exc
    finally:
        os.unlink(tmp)
