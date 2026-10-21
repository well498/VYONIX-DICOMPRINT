"""Imagens comuns (JPG, PNG, BMP) para calibração — mesmo tratamento tonal das imagens DICOM.

A imagem é convertida para float [0, 1] (tons de cinza quando os três canais são iguais) e segue
pelos mesmos ajustes (``pipeline.adjust``) e geometria do pipeline DICOM.
"""

from __future__ import annotations

from pathlib import Path

from app.imaging.decoder import DecodeError

RASTER_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp")
MAX_PIXELS = 12000 * 12000


def is_dicom(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            head = fh.read(132)
    except OSError as exc:
        raise DecodeError(f"Não foi possível abrir o arquivo: {exc.strerror or exc}") from exc
    return len(head) >= 132 and head[128:132] == b"DICM"


def kind_of(path: Path) -> str:
    """'dicom' ou 'raster'. DICOM sem preâmbulo (sem extensão) também é aceito."""
    path = Path(path)
    if is_dicom(path):
        return "dicom"
    if path.suffix.lower() in RASTER_SUFFIXES:
        return "raster"
    try:
        import pydicom
        pydicom.dcmread(path, stop_before_pixels=True, force=False)
        return "dicom"
    except Exception:  # noqa: BLE001
        pass
    try:
        from PIL import Image
        with Image.open(path) as im:
            if im.format in ("JPEG", "PNG", "BMP"):
                return "raster"
    except Exception:  # noqa: BLE001
        pass
    raise DecodeError("Formato não reconhecido. Use DICOM (.dcm ou sem extensão), JPG, PNG ou BMP.")


def load_float(path: Path):
    """(array float32 [0,1] HxW ou HxWx3, 'MONOCHROME2'|'RGB')."""
    import numpy as np
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(path) as im:
            if im.format not in ("JPEG", "PNG", "BMP"):
                raise DecodeError(f"Formato {im.format} não suportado (use JPG, PNG ou BMP).")
            if im.width * im.height > MAX_PIXELS:
                raise DecodeError(f"Imagem grande demais ({im.width} × {im.height}).")
            if im.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", im.size, (255, 255, 255))
                rgba = im.convert("RGBA")
                bg.paste(rgba, mask=rgba.split()[-1])
                im2 = bg
            elif im.mode in ("I;16", "I;16B", "I"):
                arr = np.asarray(im, dtype=np.float32)
                hi = float(arr.max()) or 1.0
                return np.clip(arr / hi, 0, 1).astype(np.float32), "MONOCHROME2"
            else:
                im2 = im.convert("RGB") if im.mode != "L" else im.copy()
    except (UnidentifiedImageError, OSError) as exc:
        raise DecodeError(f"Arquivo de imagem inválido ou corrompido: {exc}") from exc
    arr = np.asarray(im2, dtype=np.float32) / 255.0
    if arr.ndim == 3:
        if np.array_equal(arr[..., 0], arr[..., 1]) and np.array_equal(arr[..., 1], arr[..., 2]):
            return np.ascontiguousarray(arr[..., 0]), "MONOCHROME2"
        return arr, "RGB"
    return arr, "MONOCHROME2"
