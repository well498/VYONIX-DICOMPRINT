"""Assinatura Ed25519 e verificação de provas do TPM — somente via ``cryptography`` (OpenSSL).

Nada aqui implementa primitivas: são chamadas às implementações da biblioteca ``cryptography``.
"""

from __future__ import annotations

import hashlib
import struct

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

# ---------------------------------------------------------------------------- Ed25519


def public_from_hex(key_hex: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(key_hex))


def public_hex(key: Ed25519PrivateKey | Ed25519PublicKey) -> str:
    pub = key.public_key() if isinstance(key, Ed25519PrivateKey) else key
    return pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def fingerprint(key_hex: str) -> str:
    """Impressão digital curta da chave pública (exibição e conferência)."""
    h = hashlib.sha256(bytes.fromhex(key_hex)).hexdigest().upper()
    return ":".join(h[i:i + 4] for i in range(0, 24, 4))


def verify_ed25519(key_hex: str, message: bytes, signature: bytes) -> bool:
    try:
        public_from_hex(key_hex).verify(signature, message)
        return True
    except (InvalidSignature, ValueError):
        return False


def sign_ed25519(private: Ed25519PrivateKey, message: bytes) -> bytes:
    return private.sign(message)


def generate_ed25519() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def private_to_pem(private: Ed25519PrivateKey, passphrase: bytes) -> bytes:
    """PKCS#8 cifrado com a frase-senha (PBES2 da ``cryptography``). Nunca sem cifra."""
    if not passphrase or len(passphrase) < 10:
        raise ValueError("A frase-senha da chave deve ter pelo menos 10 caracteres.")
    return private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                 serialization.BestAvailableEncryption(passphrase))


def private_from_pem(pem: bytes, passphrase: bytes) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(pem, password=passphrase)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("A chave não é Ed25519.")
    return key


# ---------------------------------------------------------------------------- TPM (prova de posse)
# Formatos de chave pública exportados pelo Windows CNG (bcrypt.h):
#   BCRYPT_ECCPUBLIC_BLOB  = {ULONG dwMagic; ULONG cbKey} || X || Y      (ECDSA P-256: magic "ECS1")
#   BCRYPT_RSAPUBLIC_BLOB  = {Magic, BitLength, cbPublicExp, cbModulus, cbPrime1, cbPrime2} || e || n
ECDSA_P256_PUBLIC_MAGIC = 0x31534345
RSA_PUBLIC_MAGIC = 0x31415352


def tpm_public_key(alg: str, blob: bytes):
    if alg == "ECDSA_P256":
        magic, cb = struct.unpack_from("<II", blob, 0)
        if magic != ECDSA_P256_PUBLIC_MAGIC or cb != 32 or len(blob) < 8 + 64:
            raise ValueError("Chave pública ECC do TPM em formato inesperado.")
        x = int.from_bytes(blob[8:40], "big")
        y = int.from_bytes(blob[40:72], "big")
        return ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()
    if alg == "RSA":
        magic, _bits, cb_exp, cb_mod, _p1, _p2 = struct.unpack_from("<IIIIII", blob, 0)
        if magic != RSA_PUBLIC_MAGIC:
            raise ValueError("Chave pública RSA do TPM em formato inesperado.")
        off = 24
        e = int.from_bytes(blob[off:off + cb_exp], "big")
        n = int.from_bytes(blob[off + cb_exp:off + cb_exp + cb_mod], "big")
        return rsa.RSAPublicNumbers(e, n).public_key()
    raise ValueError(f"Algoritmo de TPM não suportado: {alg}")


def verify_tpm(alg: str, blob: bytes, digest32: bytes, signature: bytes) -> bool:
    """Verifica uma assinatura feita pelo TPM sobre um resumo SHA-256 (``NCryptSignHash``)."""
    try:
        key = tpm_public_key(alg, blob)
        if alg == "ECDSA_P256":
            if len(signature) != 64:
                return False
            der = encode_dss_signature(int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big"))
            key.verify(der, digest32, ec.ECDSA(_Prehashed()))
        else:
            key.verify(signature, digest32, padding.PKCS1v15(), _Prehashed())
        return True
    except (InvalidSignature, ValueError, struct.error):
        return False


def _Prehashed():  # noqa: N802 - fábrica de objeto da biblioteca
    from cryptography.hazmat.primitives.asymmetric.utils import Prehashed
    return Prehashed(hashes.SHA256())


def tpm_key_digest(alg: str, blob: bytes) -> str:
    """Identidade da chave do TPM usada como componente do Hardware ID."""
    return hashlib.sha256(b"VYONIX/tpm-key/v1|" + alg.encode() + b"|" + blob).hexdigest()
