"""Verificação de assinaturas Ed25519 (RFC 8032) em Python puro.

O aplicativo do cliente só **verifica** assinaturas: não contém nem gera chave privada. A emissão
fica na ferramenta separada ``license_admin`` (que usa a biblioteca ``cryptography``). Mantido em
Python puro para não acrescentar dependências nativas ao pacote; a correção é verificada nos testes
com os vetores oficiais da RFC 8032 e com assinaturas geradas pela ``cryptography``.

Baseado na implementação de referência da RFC 8032, seção 6 (domínio público).
"""

from __future__ import annotations

import hashlib

_p = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_d = -121665 * pow(121666, _p - 2, _p) % _p
_SQRT_M1 = pow(2, (_p - 1) // 4, _p)


def _sha512(data: bytes) -> bytes:
    return hashlib.sha512(data).digest()


def _add(P, Q):
    A = (P[1] - P[0]) * (Q[1] - Q[0]) % _p
    B = (P[1] + P[0]) * (Q[1] + Q[0]) % _p
    C = 2 * P[3] * Q[3] * _d % _p
    D = 2 * P[2] * Q[2] % _p
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F % _p, G * H % _p, F * G % _p, E * H % _p)


def _mul(s: int, P):
    Q = (0, 1, 1, 0)   # elemento neutro
    while s > 0:
        if s & 1:
            Q = _add(Q, P)
        P = _add(P, P)
        s >>= 1
    return Q


def _equal(P, Q) -> bool:
    if (P[0] * Q[2] - Q[0] * P[2]) % _p != 0:
        return False
    return (P[1] * Q[2] - Q[1] * P[2]) % _p == 0


def _recover_x(y: int, sign: int) -> int | None:
    if y >= _p:
        return None
    x2 = (y * y - 1) * pow(_d * y * y + 1, _p - 2, _p)
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_p + 3) // 8, _p)
    if (x * x - x2) % _p != 0:
        x = x * _SQRT_M1 % _p
    if (x * x - x2) % _p != 0:
        return None
    if (x & 1) != sign:
        x = _p - x
    return x


def _decompress(s: bytes):
    if len(s) != 32:
        raise ValueError("ponto deve ter 32 bytes")
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _p)


_gy = 4 * pow(5, _p - 2, _p) % _p
_gx = _recover_x(_gy, 0)
_G = (_gx, _gy, 1, _gx * _gy % _p)


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """True se ``signature`` é uma assinatura Ed25519 válida de ``message`` por ``public_key``."""
    if len(public_key) != 32 or len(signature) != 64:
        return False
    A = _decompress(public_key)
    if A is None:
        return False
    R_bytes = signature[:32]
    R = _decompress(R_bytes)
    if R is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    h = int.from_bytes(_sha512(R_bytes + public_key + message), "little") % _L
    return _equal(_mul(s, _G), _add(R, _mul(h, A)))
