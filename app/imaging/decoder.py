"""Leitura de metadados e decodificação de Pixel Data (§6 itens 1–4, 20, 21, 25).

* Lê **um quadro por vez** (``pydicom.pixels.pixel_array(path, index=i)``): estudos multiframe
  não são carregados inteiros na memória.
* Metadados de apresentação ficam em :class:`ImageInfo`, sem dados demográficos.
* Arquivos inválidos, incompletos ou com compressão sem decodificador geram
  :class:`DecodeError` com mensagem clara — nunca uma exceção genérica.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.errors import VyonixError
from app.dicom import sop

MONOCHROME = ("MONOCHROME1", "MONOCHROME2")


class DecodeError(VyonixError):
    """A imagem não pôde ser lida ou decodificada."""


@dataclass(frozen=True)
class ImageInfo:
    sop_instance_uid: str
    sop_class_uid: str
    modality: str
    transfer_syntax: str
    rows: int
    columns: int
    frames: int
    samples_per_pixel: int
    photometric: str
    bits_allocated: int
    bits_stored: int
    pixel_representation: int
    rescale_slope: float
    rescale_intercept: float
    has_modality_lut: bool
    window_centers: tuple[float, ...]
    window_widths: tuple[float, ...]
    window_explanations: tuple[str, ...]
    voi_lut_count: int
    voi_lut_function: str
    presentation_lut_shape: str
    pixel_spacing_mm: tuple[float, float] | None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_color(self) -> bool:
        return self.samples_per_pixel == 3 or self.photometric == "PALETTE COLOR"


def _floats(value: Any) -> tuple[float, ...]:
    if value is None or value == "":
        return ()
    try:
        seq = list(value) if hasattr(value, "__iter__") and not isinstance(value, (str, bytes)) else [value]
        return tuple(float(v) for v in seq)
    except (TypeError, ValueError):
        return ()


def _spacing(ds) -> tuple[float, float] | None:
    for key in ("PixelSpacing", "ImagerPixelSpacing", "NominalScannedPixelSpacing"):
        values = _floats(ds.get(key))
        if len(values) == 2 and all(v > 0 for v in values):
            return values  # (linha, coluna) em mm
    return None


def read_dataset(path: Path, *, with_pixels: bool = False):
    from pydicom import dcmread
    from pydicom.errors import InvalidDicomError
    try:
        return dcmread(str(path), stop_before_pixels=not with_pixels)
    except FileNotFoundError as exc:
        raise DecodeError(f"Arquivo não encontrado: {Path(path).name}") from exc
    except (InvalidDicomError, EOFError, ValueError, OSError) as exc:
        raise DecodeError(f"Arquivo DICOM inválido ou incompleto: {type(exc).__name__}") from exc


def info_from_dataset(ds) -> ImageInfo:
    meta = getattr(ds, "file_meta", None)
    if "Rows" not in ds or "Columns" not in ds:
        raise DecodeError("O arquivo não contém imagem (Rows/Columns ausentes).")
    shape = str(ds.get("PresentationLUTShape", "") or "").upper()
    expl = ds.get("WindowCenterWidthExplanation", ())
    if isinstance(expl, str):
        expl = (expl,)
    return ImageInfo(
        sop_instance_uid=str(ds.get("SOPInstanceUID", "")),
        sop_class_uid=str(ds.get("SOPClassUID", "")),
        modality=str(ds.get("Modality", "") or ""),
        transfer_syntax=str(meta.get("TransferSyntaxUID", "")) if meta else "",
        rows=int(ds.Rows), columns=int(ds.Columns),
        frames=int(ds.get("NumberOfFrames", 1) or 1),
        samples_per_pixel=int(ds.get("SamplesPerPixel", 1) or 1),
        photometric=str(ds.get("PhotometricInterpretation", "MONOCHROME2")).upper(),
        bits_allocated=int(ds.get("BitsAllocated", 16) or 16),
        bits_stored=int(ds.get("BitsStored", ds.get("BitsAllocated", 16)) or 16),
        pixel_representation=int(ds.get("PixelRepresentation", 0) or 0),
        rescale_slope=float(ds.get("RescaleSlope", 1) or 1),
        rescale_intercept=float(ds.get("RescaleIntercept", 0) or 0),
        has_modality_lut=bool(ds.get("ModalityLUTSequence")),
        window_centers=_floats(ds.get("WindowCenter")),
        window_widths=_floats(ds.get("WindowWidth")),
        window_explanations=tuple(str(e) for e in expl),
        voi_lut_count=len(ds.get("VOILUTSequence", []) or []),
        voi_lut_function=str(ds.get("VOILUTFunction", "LINEAR") or "LINEAR").upper(),
        presentation_lut_shape=shape,
        pixel_spacing_mm=_spacing(ds),
    )


def read_info(path: Path) -> ImageInfo:
    return info_from_dataset(read_dataset(path))


def decode_frame(path: Path, frame: int = 0):
    """Retorna (dataset sem pixels, ndarray do quadro). Cor já convertida para RGB."""
    from pydicom.pixels import pixel_array

    ds = read_dataset(path)
    info = info_from_dataset(ds)
    if not 0 <= frame < info.frames:
        raise DecodeError(f"Quadro {frame + 1} inexistente (a imagem tem {info.frames}).")
    ts = info.transfer_syntax
    try:
        arr = pixel_array(str(path), index=frame if info.frames > 1 else None)
    except NotImplementedError as exc:
        raise DecodeError(f"Compressão não suportada: {sop.TRANSFER_SYNTAX_NAMES.get(ts, ts)}.") from exc
    except RuntimeError as exc:
        msg = str(exc)
        if "plugin" in msg.lower() or "decoder" in msg.lower() or "available" in msg.lower():
            raise DecodeError(f"Sem decodificador para {sop.TRANSFER_SYNTAX_NAMES.get(ts, ts)}.") from exc
        raise DecodeError(f"Falha ao decodificar a imagem: {msg[:200]}") from exc
    except (ValueError, KeyError, AttributeError, EOFError) as exc:
        raise DecodeError(f"Imagem incompleta ou inconsistente: {type(exc).__name__}: {str(exc)[:160]}") from exc
    if info.frames > 1 and arr.ndim == (4 if info.samples_per_pixel == 3 else 3):
        arr = arr[0]
    return ds, info, arr
