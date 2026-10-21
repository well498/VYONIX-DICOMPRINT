"""Chave não exportável no TPM 2.0 (Microsoft Platform Crypto Provider) e prova de posse.

O VYONIX cria, uma única vez por computador (na instalação, com privilégios de administrador),
uma chave de máquina ECDSA P-256 — ou RSA 2048 se o TPM não oferecer ECC — dentro do TPM. A chave
privada nunca sai do chip: o arquivo que o Windows guarda é cifrado pela hierarquia do próprio TPM
e não funciona em outro computador. A identidade da chave (resumo da chave pública) é um
componente do Hardware ID; a licença que a inclui só é aceita se o TPM **assinar um desafio
aleatório** e a assinatura for verificada com a chave pública (``vyonix_protocol.crypto``).

A chave é preservada na desinstalação: ela identifica o computador, não a instalação.

Chamadas ao Windows por ``ctypes`` (ncrypt.dll/advapi32.dll). Em computadores sem TPM 2.0 (ou com
o TPM desativado no firmware) a camada fica indisponível e é informada como tal.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
from ctypes import wintypes
from typing import Any

log = logging.getLogger(__name__)

KEY_NAME = "VYONIX-DICOM-Print-Device-v2"
PROVIDER = "Microsoft Platform Crypto Provider"
NCRYPT_MACHINE_KEY_FLAG = 0x20
NCRYPT_SILENT_FLAG = 0x40
NTE_BAD_KEYSET = 0x80090016
NTE_EXISTS = 0x8009000F
DACL_SECURITY_INFORMATION = 0x4
# SYSTEM e Administradores: controle total; Usuários: uso da chave (a interface roda como usuário comum).
KEY_SDDL = "D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GA;;;BU)"
BCRYPT_PAD_PKCS1 = 0x2


def _hr(status: int) -> int:
    return status & 0xFFFFFFFF


class TpmError(Exception):
    def __init__(self, what: str, status: int | None = None) -> None:
        self.status = None if status is None else _hr(status)
        super().__init__(f"{what}" + (f" (0x{self.status:08X})" if self.status is not None else ""))


class NullTpm:
    """Sem TPM (outros sistemas ou desativado por configuração)."""

    def __init__(self, reason: str = "TPM não disponível neste sistema") -> None:
        self.reason = reason

    def info(self) -> dict[str, Any]:
        return {"available": False, "reason": self.reason}

    def sign(self, digest32: bytes) -> bytes:
        raise TpmError(self.reason)

    def provision(self) -> dict[str, Any]:
        return self.info()


class _BCRYPT_PKCS1_PADDING_INFO(ctypes.Structure):
    _fields_ = [("pszAlgId", wintypes.LPCWSTR)]


class WindowsTpm:
    """Chave de máquina no Microsoft Platform Crypto Provider."""

    def __init__(self, key_name: str = KEY_NAME) -> None:
        self.key_name = key_name
        self._lock = threading.Lock()
        self._info: dict[str, Any] | None = None
        self.ncrypt = ctypes.WinDLL("ncrypt.dll")
        H = ctypes.c_size_t
        n = self.ncrypt
        n.NCryptOpenStorageProvider.argtypes = [ctypes.POINTER(H), wintypes.LPCWSTR, wintypes.DWORD]
        n.NCryptOpenKey.argtypes = [H, ctypes.POINTER(H), wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        n.NCryptCreatePersistedKey.argtypes = [H, ctypes.POINTER(H), wintypes.LPCWSTR, wintypes.LPCWSTR,
                                               wintypes.DWORD, wintypes.DWORD]
        n.NCryptSetProperty.argtypes = [H, wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD]
        n.NCryptFinalizeKey.argtypes = [H, wintypes.DWORD]
        n.NCryptExportKey.argtypes = [H, H, wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                                      ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
        n.NCryptSignHash.argtypes = [H, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                                     wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
        n.NCryptGetProperty.argtypes = [H, wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD,
                                        ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
        n.NCryptFreeObject.argtypes = [H]
        for f in ("NCryptOpenStorageProvider", "NCryptOpenKey", "NCryptCreatePersistedKey", "NCryptSetProperty",
                  "NCryptFinalizeKey", "NCryptExportKey", "NCryptSignHash", "NCryptFreeObject", "NCryptGetProperty"):
            getattr(n, f).restype = ctypes.c_long

    # ---------------------------------------------------------------- baixo nível
    def _provider(self):
        h = ctypes.c_size_t()
        st = self.ncrypt.NCryptOpenStorageProvider(ctypes.byref(h), PROVIDER, 0)
        if st != 0:
            raise TpmError("Provedor de criptografia do TPM indisponível", st)
        return h

    def _open(self, prov):
        k = ctypes.c_size_t()
        st = self.ncrypt.NCryptOpenKey(prov, ctypes.byref(k), self.key_name, 0,
                                       NCRYPT_MACHINE_KEY_FLAG | NCRYPT_SILENT_FLAG)
        if st != 0:
            raise TpmError("Chave do VYONIX no TPM não encontrada ou inacessível", st)
        return k

    def _alg_of(self, key) -> str:
        buf = ctypes.create_unicode_buffer(64)
        cb = wintypes.DWORD()
        st = self.ncrypt.NCryptGetProperty(key, "Algorithm Group", buf, ctypes.sizeof(buf), ctypes.byref(cb), 0)
        if st != 0:
            raise TpmError("Não foi possível ler o algoritmo da chave do TPM", st)
        return "RSA" if buf.value.upper() == "RSA" else "ECDSA_P256"

    def _export(self, key, alg: str) -> bytes:
        blob_type = "RSAPUBLICBLOB" if alg == "RSA" else "ECCPUBLICBLOB"
        cb = wintypes.DWORD()
        st = self.ncrypt.NCryptExportKey(key, 0, blob_type, None, None, 0, ctypes.byref(cb), 0)
        if st != 0:
            raise TpmError("Falha ao exportar a chave pública do TPM", st)
        buf = (ctypes.c_ubyte * cb.value)()
        st = self.ncrypt.NCryptExportKey(key, 0, blob_type, None, buf, cb.value, ctypes.byref(cb), 0)
        if st != 0:
            raise TpmError("Falha ao exportar a chave pública do TPM", st)
        return bytes(buf[:cb.value])

    def _create(self, prov, alg: str):
        k = ctypes.c_size_t()
        st = self.ncrypt.NCryptCreatePersistedKey(prov, ctypes.byref(k), "RSA" if alg == "RSA" else "ECDSA_P256",
                                                  self.key_name, 0, NCRYPT_MACHINE_KEY_FLAG)
        if st != 0:
            raise TpmError("O TPM recusou a criação da chave", st)
        try:
            if alg == "RSA":
                length = wintypes.DWORD(2048)
                self.ncrypt.NCryptSetProperty(k, "Length", ctypes.byref(length), 4, 0)
            self._set_dacl(k)
            st = self.ncrypt.NCryptFinalizeKey(k, 0)
            if st != 0:
                raise TpmError("O TPM não concluiu a criação da chave", st)
        except Exception:
            self.ncrypt.NCryptFreeObject(k)
            raise
        return k

    def _set_dacl(self, key) -> None:
        adv = ctypes.WinDLL("advapi32.dll")
        psd = ctypes.c_void_p()
        size = wintypes.ULONG()
        conv = adv.ConvertStringSecurityDescriptorToSecurityDescriptorW
        conv.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
                         ctypes.POINTER(wintypes.ULONG)]
        if not conv(KEY_SDDL, 1, ctypes.byref(psd), ctypes.byref(size)):
            return
        try:
            st = self.ncrypt.NCryptSetProperty(key, "Security Descr", psd, size.value, DACL_SECURITY_INFORMATION)
            if st != 0:
                log.info("Permissões da chave do TPM não aplicadas (0x%08X)", _hr(st))
        finally:
            ctypes.windll.kernel32.LocalFree(psd)

    # ---------------------------------------------------------------- API
    def info(self, refresh: bool = False) -> dict[str, Any]:
        with self._lock:
            if self._info is not None and not refresh:
                return dict(self._info)
        try:
            prov = self._provider()
        except TpmError as exc:
            res = {"available": False, "reason": "TPM 2.0 ausente ou desativado", "detail": str(exc)}
        else:
            try:
                key = self._open(prov)
            except TpmError as exc:
                missing = exc.status == NTE_BAD_KEYSET
                res = {"available": False, "present": not missing,
                       "reason": "chave do VYONIX ainda não criada no TPM" if missing
                       else "chave do TPM inacessível para este usuário", "detail": str(exc)}
            else:
                try:
                    alg = self._alg_of(key)
                    res = {"available": True, "alg": alg, "pub": self._export(key, alg)}
                except TpmError as exc:
                    res = {"available": False, "reason": "chave do TPM ilegível", "detail": str(exc)}
                finally:
                    self.ncrypt.NCryptFreeObject(key)
            finally:
                self.ncrypt.NCryptFreeObject(prov)
        with self._lock:
            self._info = res
        return dict(res)

    def provision(self) -> dict[str, Any]:
        """Cria a chave se ela não existir (requer administrador/Sistema Local). Idempotente."""
        cur = self.info(refresh=True)
        if cur.get("available") or cur.get("present"):
            return cur
        try:
            prov = self._provider()
        except TpmError as exc:
            return {"available": False, "reason": "TPM 2.0 ausente ou desativado", "detail": str(exc)}
        try:
            last = None
            for alg in ("ECDSA_P256", "RSA"):
                try:
                    k = self._create(prov, alg)
                    self.ncrypt.NCryptFreeObject(k)
                    last = None
                    break
                except TpmError as exc:
                    if exc.status == NTE_EXISTS:
                        last = None
                        break
                    last = exc
            if last is not None:
                return {"available": False, "reason": "o TPM recusou a criação da chave", "detail": str(last)}
        finally:
            self.ncrypt.NCryptFreeObject(prov)
        return self.info(refresh=True)

    def sign(self, digest32: bytes) -> bytes:
        if len(digest32) != 32:
            raise ValueError("O desafio deve ser um resumo SHA-256.")
        prov = self._provider()
        try:
            key = self._open(prov)
            try:
                alg = self._alg_of(key)
                pad = None
                flags = 0
                if alg == "RSA":
                    info = _BCRYPT_PKCS1_PADDING_INFO("SHA256")
                    pad = ctypes.byref(info)
                    flags = BCRYPT_PAD_PKCS1
                h = (ctypes.c_ubyte * 32).from_buffer_copy(digest32)
                cb = wintypes.DWORD()
                st = self.ncrypt.NCryptSignHash(key, pad, h, 32, None, 0, ctypes.byref(cb), flags)
                if st != 0:
                    raise TpmError("O TPM não assinou o desafio", st)
                sig = (ctypes.c_ubyte * cb.value)()
                st = self.ncrypt.NCryptSignHash(key, pad, h, 32, sig, cb.value, ctypes.byref(cb), flags)
                if st != 0:
                    raise TpmError("O TPM não assinou o desafio", st)
                return bytes(sig[:cb.value])
            finally:
                self.ncrypt.NCryptFreeObject(key)
        finally:
            self.ncrypt.NCryptFreeObject(prov)


def default_tpm():
    if os.environ.get("VYONIX_TPM", "1") == "0":
        return NullTpm("TPM desativado pela configuração")
    if sys.platform != "win32":
        return NullTpm()
    try:
        return WindowsTpm()
    except OSError as exc:
        return NullTpm(f"ncrypt.dll indisponível: {exc}")


def prove(tpm, alg: str, pub: bytes) -> tuple[bool, str]:
    """Prova de posse: o TPM assina um desafio novo e a assinatura é verificada fora do TPM."""
    import hashlib
    import secrets
    from vyonix_protocol.crypto import verify_tpm
    challenge = hashlib.sha256(b"VYONIX/tpm-proof/v1|" + secrets.token_bytes(32)).digest()
    try:
        sig = tpm.sign(challenge)
    except Exception as exc:  # noqa: BLE001
        return False, f"o TPM não respondeu ao desafio ({exc})"
    if not verify_tpm(alg, pub, challenge, sig):
        return False, "a assinatura do TPM não confere com a chave autorizada"
    return True, "prova de posse do TPM verificada"
