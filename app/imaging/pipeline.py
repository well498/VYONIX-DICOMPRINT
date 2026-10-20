"""Pipeline de apresentação (§6) — implementa ``core.contracts.ImagePipeline``.

Ordem, conforme o modelo de apresentação do DICOM (PS3.3 C.11, PS3.4 N.2):

1. **Modality LUT**: Rescale Slope/Intercept ou Modality LUT Sequence → valores de modalidade.
2. **VOI**: janela informada pelo usuário; senão a primeira janela do arquivo (Window Center/
   Width, função LINEAR, LINEAR_EXACT ou SIGMOID); senão a VOI LUT Sequence; senão a faixa
   completa de valores. A escolha é registrada em ``applied``.
3. **Presentation LUT / fotometria**: MONOCHROME1 (ou Presentation LUT Shape INVERSE em
   MONOCHROME2) é invertida para que "valor alto = claro" no resultado.
4. **Ajustes explícitos**: inversão, brilho, contraste e gama — somente se solicitados.
5. **Geometria**: recorte, rotação em múltiplos de 90° e espelhamento.

Cálculos em float32 (nunca float64), saída uint8 (cinza HxW ou RGB HxWx3).
Nenhum ajuste que altere a interpretação diagnóstica é aplicado automaticamente.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.core.contracts import PresentationParams, RenderedImage
from app.imaging.decoder import MONOCHROME, DecodeError, ImageInfo, decode_frame


def _np():
    import numpy as np
    return np


def modality_values(arr, ds, info: ImageInfo):
    np = _np()
    if info.has_modality_lut:
        from pydicom.pixels import apply_modality_lut
        return apply_modality_lut(arr, ds).astype(np.float32, copy=False), "Modality LUT Sequence"
    out = arr.astype(np.float32, copy=False)
    if info.rescale_slope != 1 or info.rescale_intercept != 0:
        out = out * np.float32(info.rescale_slope) + np.float32(info.rescale_intercept)
        return out, f"Rescale slope={info.rescale_slope:g} intercept={info.rescale_intercept:g}"
    return out, "identidade"


def window(values, center: float, width: float, function: str = "LINEAR"):
    """Janela normalizada para [0, 1] (PS3.3 C.11.2.1.2)."""
    np = _np()
    c, w = np.float32(center), np.float32(width)
    function = (function or "LINEAR").upper()
    if function == "SIGMOID":
        w = max(w, np.float32(1e-6))
        return (1.0 / (1.0 + np.exp(-4.0 * (values - c) / w))).astype(np.float32)
    if function == "LINEAR_EXACT":
        w = max(w, np.float32(1e-6))
        out = (values - c) / w + 0.5
    else:  # LINEAR
        w = max(w, np.float32(1.0))
        out = ((values - (c - 0.5)) / (w - 1.0)) + 0.5
    return np.clip(out, 0.0, 1.0).astype(np.float32, copy=False)


def voi(values, arr, ds, info: ImageInfo, params: PresentationParams):
    np = _np()
    if params.window_center is not None and params.window_width is not None:
        return window(values, params.window_center, params.window_width, info.voi_lut_function), {
            "voi": "janela informada", "center": params.window_center, "width": params.window_width}
    if params.voi_lut_index is not None and info.voi_lut_count:
        return _voi_lut(values, ds, params.voi_lut_index)
    if info.window_centers and info.window_widths:
        return window(values, info.window_centers[0], info.window_widths[0], info.voi_lut_function), {
            "voi": "janela do arquivo", "center": info.window_centers[0], "width": info.window_widths[0],
            "function": info.voi_lut_function}
    if info.voi_lut_count:
        return _voi_lut(values, ds, 0)
    lo, hi = float(np.min(values)), float(np.max(values))
    if hi <= lo:
        return np.zeros_like(values, dtype=np.float32), {"voi": "faixa completa (imagem uniforme)"}
    return ((values - lo) / (hi - lo)).astype(np.float32), {"voi": "faixa completa", "min": lo, "max": hi}


def _voi_lut(values, ds, index: int):
    np = _np()
    from pydicom.pixels import apply_voi_lut
    item = ds.VOILUTSequence[index]
    bits = int(item.LUTDescriptor[2])
    out = apply_voi_lut(values.astype(np.int64), ds, index=index, prefer_lut=True).astype(np.float32)
    return np.clip(out / float(2 ** bits - 1), 0, 1), {"voi": f"VOI LUT Sequence #{index + 1}"}


def adjust(v, params: PresentationParams):
    """Ajustes explícitos sobre valores normalizados [0, 1]."""
    np = _np()
    applied: dict[str, Any] = {}
    if params.invert:
        v = 1.0 - v
        applied["invert"] = True
    if params.contrast != 1.0:
        v = (v - 0.5) * np.float32(params.contrast) + 0.5
        applied["contrast"] = params.contrast
    if params.brightness:
        v = v + np.float32(params.brightness)
        applied["brightness"] = params.brightness
    v = np.clip(v, 0.0, 1.0)
    if params.gamma != 1.0:
        v = np.power(v, np.float32(1.0 / max(params.gamma, 0.05)))
        applied["gamma"] = params.gamma
    return v, applied


def geometry(img, params: PresentationParams):
    np = _np()
    applied: dict[str, Any] = {}
    if params.crop:
        x, y, w, h = params.crop
        H, W = img.shape[:2]
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(W, x + w), min(H, y + h)
        if x1 <= x0 or y1 <= y0:
            raise DecodeError("Recorte fora da imagem.")
        img = img[y0:y1, x0:x1]
        applied["crop"] = (x0, y0, x1 - x0, y1 - y0)
    turns = (params.rotate_degrees // 90) % 4
    if params.rotate_degrees % 90:
        raise DecodeError("A rotação deve ser múltipla de 90°.")
    if turns:
        img = np.rot90(img, k=-turns)   # sentido horário
        applied["rotate"] = turns * 90
    if params.flip_horizontal:
        img = img[:, ::-1]
        applied["flip_horizontal"] = True
    if params.flip_vertical:
        img = img[::-1, :]
        applied["flip_vertical"] = True
    return np.ascontiguousarray(img), applied


def to_uint8(v):
    np = _np()
    return (np.clip(v, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


class PresentationPipeline:
    """Renderiza uma instância DICOM para impressão ou pré-visualização."""

    def render(self, source: Path, params: PresentationParams | None = None) -> RenderedImage:
        np = _np()
        params = params or PresentationParams()
        ds, info, arr = decode_frame(Path(source), params.frame_index)
        applied: dict[str, Any] = {"frame": params.frame_index, "frames": info.frames,
                                   "photometric": info.photometric}
        if info.photometric in MONOCHROME and info.samples_per_pixel == 1:
            values, mlut = modality_values(arr, ds, info)
            applied["modality_lut"] = mlut
            v, voi_applied = voi(values, arr, ds, info, params)
            applied.update(voi_applied)
            inverse = info.photometric == "MONOCHROME1" or info.presentation_lut_shape == "INVERSE"
            if inverse:
                v = 1.0 - v
                applied["presentation"] = ("MONOCHROME1" if info.photometric == "MONOCHROME1"
                                           else "Presentation LUT INVERSE")
            photometric = "MONOCHROME2"
        else:
            if info.photometric == "PALETTE COLOR":
                from pydicom.pixels import apply_color_lut
                arr = apply_color_lut(arr, ds)
                applied["color"] = "Palette Color LUT"
            elif arr.ndim == 2:
                arr = np.stack([arr] * 3, axis=-1)
            if arr.dtype == np.uint8:
                maxv = 255.0
            else:
                bits = 16 if info.photometric == "PALETTE COLOR" else min(max(info.bits_stored, 1), 16)
                maxv = float(2 ** bits - 1)
            v = arr.astype(np.float32) / np.float32(maxv)
            photometric = "RGB"
        v, adj = adjust(v, params)
        applied.update(adj)
        img, geo = geometry(to_uint8(v), params)
        applied.update(geo)
        spacing = info.pixel_spacing_mm
        if spacing and (params.rotate_degrees // 90) % 2:
            spacing = (spacing[1], spacing[0])
        applied["params"] = asdict(params)
        return RenderedImage(pixels=img, photometric=photometric, pixel_spacing_mm=spacing, applied=applied)
