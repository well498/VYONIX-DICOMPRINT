"""Detecção dos decodificadores de Pixel Data disponíveis neste executável.

Usado pelo Storage SCP para aceitar somente sintaxes comprimidas que conseguimos decodificar.
Todos os testes são de importação (rápidos e sem efeito colateral).
"""

from __future__ import annotations

import importlib.util
from functools import lru_cache

from app.dicom import sop


def _has(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


@lru_cache(maxsize=1)
def available() -> dict[str, bool]:
    numpy = _has("numpy")
    pillow = _has("PIL")
    return {
        "numpy": numpy,
        "pillow": pillow,
        "pylibjpeg-openjpeg": _has("openjpeg"),
        "pylibjpeg-rle": _has("rle"),
        "pyjpegls": _has("jpeg_ls"),
        "pylibjpeg-libjpeg": _has("libjpeg"),
        "gdcm": _has("gdcm"),
    }


@lru_cache(maxsize=1)
def decodable_compressed() -> list[str]:
    a = available()
    if not a["numpy"]:          # sem numpy o pydicom não decodifica nenhum Pixel Data
        return []
    out = [sop.RLE_LOSSLESS]    # decodificador nativo do pydicom 3
    if a["pillow"]:
        out += [sop.JPEG_BASELINE, sop.JPEG_EXTENDED]
    if a["pylibjpeg-openjpeg"] or a["gdcm"]:
        out += [sop.JPEG_2000_LOSSLESS, sop.JPEG_2000]
    if a["pyjpegls"] or a["gdcm"]:
        out += [sop.JPEG_LS_LOSSLESS, sop.JPEG_LS_LOSSY]
    if a["pylibjpeg-libjpeg"] or a["gdcm"]:
        out += [sop.JPEG_LOSSLESS, sop.JPEG_LOSSLESS_SV1]
    return out
