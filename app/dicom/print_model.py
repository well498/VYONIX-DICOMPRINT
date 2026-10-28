"""Modelo do DICOM Print Management (PS3.4 Anexo H) por associação.

Hierarquia: Film Session → Film Box → Image Box (+ Presentation LUT opcional). Este módulo
não conhece rede nem banco: recebe os datasets das operações N-CREATE/N-SET/N-ACTION/N-DELETE/
N-GET e devolve ``(status, dataset de resposta)``. O Print SCP faz a ponte com o pynetdicom e a
fila de impressão.

Suporte nesta versão (declarado na Declaração de Conformidade):

* Basic Grayscale e Basic Color Print Management Meta SOP Classes;
* Presentation LUT (formas IDENTITY e LIN OD; LUT explícita);
* Image Display Format ``STANDARD\\C,R`` de 1×1 a 8×8 (ROW/COL/SLIDE/SUPERSLIDE/CUSTOM recusados
  com 0x0106 — nunca impressos de forma diferente da pedida);
* N-ACTION de impressão no Film Box e no Film Session;
* Printer SOP Instance (N-GET).

Não suportado: Basic Annotation Box, Print Job SOP Class (sem ``Referenced Print Job Sequence``),
Image Overlay Box, VOI LUT Box. A densidade (Min/Max Density, Border/Empty Image Density) é
registrada e só é aplicada se a configuração ``dicom.print.honor_density`` estiver ligada, pois
impressoras de papel não reproduzem densidade óptica de filme.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from app.utils.logging_setup import get_logger

log = get_logger("dicom.print")

# SOP Classes
GRAYSCALE_META = "1.2.840.10008.5.1.1.9"
COLOR_META = "1.2.840.10008.5.1.1.18"
FILM_SESSION = "1.2.840.10008.5.1.1.1"
FILM_BOX = "1.2.840.10008.5.1.1.2"
GRAY_IMAGE_BOX = "1.2.840.10008.5.1.1.4"
COLOR_IMAGE_BOX = "1.2.840.10008.5.1.1.4.1"
PRINTER = "1.2.840.10008.5.1.1.16"
PRINTER_INSTANCE = "1.2.840.10008.5.1.1.17"
PRESENTATION_LUT = "1.2.840.10008.5.1.1.23"
ANNOTATION_BOX = "1.2.840.10008.5.1.1.15"
PRINT_JOB = "1.2.840.10008.5.1.1.14"

# Status (PS3.4 H.4)
SUCCESS = 0x0000
NO_SUCH_INSTANCE = 0x0112
INVALID_VALUE = 0x0106
NO_SUCH_SOP_CLASS = 0x0118
MISSING_ATTRIBUTE = 0x0120
PROCESSING_FAILURE = 0x0110
NO_SUCH_ACTION = 0x0123
DUPLICATE_INSTANCE = 0x0111
RESOURCE_LIMITATION = 0x0213
WARN_EMPTY_SESSION = 0xB602
WARN_EMPTY_FILMBOX = 0xB603
WARN_MEMORY_ALLOC = 0xB600
FAIL_FILMBOX_NOT_PRINTED = 0xC616
FAIL_IMAGE_SIZE = 0xC603           # imagem maior que a célula / sem memória
FAIL_POSITION = 0xC605             # posição inexistente (não padronizado como erro geral)

FORMAT_RE = re.compile(r"^\s*STANDARD\\\s*(\d+)\s*,\s*(\d+)\s*$", re.I)
MAX_IMAGE_BYTES = 64 * 1024 * 1024

# Atributos técnicos guardados para auditoria (nada de rótulos livres, que podem ter nomes).
SESSION_KEYS = ("NumberOfCopies", "PrintPriority", "MediumType", "FilmDestination", "MemoryAllocation")
FILMBOX_KEYS = ("ImageDisplayFormat", "FilmOrientation", "FilmSizeID", "MagnificationType", "SmoothingType",
                "BorderDensity", "EmptyImageDensity", "MinDensity", "MaxDensity", "Trim",
                "ConfigurationInformation", "Illumination", "ReflectedAmbientLight", "RequestedResolutionID")


def _uid() -> str:
    from app.dicom.uids import new_uid
    return new_uid()


def _attrs(ds, keys) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if ds is None:
        return out
    for k in keys:
        if k in ds and ds.get(k) not in (None, ""):
            v = ds.get(k)
            out[k] = v if isinstance(v, (int, float)) else str(v)
    return out


@dataclass
class ImageBox:
    uid: str
    position: int
    film_box: str
    color: bool
    pixels: Any = None                 # numpy uint8 (H×W ou H×W×3), valores de apresentação
    polarity: str = "NORMAL"
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class FilmBox:
    uid: str
    rows: int
    cols: int
    attrs: dict[str, Any]
    image_boxes: list[str] = field(default_factory=list)
    presentation_lut: str | None = None
    printed: bool = False


@dataclass
class PresentationLut:
    uid: str
    shape: str | None
    table: Any = None                  # numpy (entradas → saída normalizada 0..1)


@dataclass
class PrintedFilm:
    """Resultado de um N-ACTION de impressão: o que a fila precisa para criar o trabalho."""

    film_session: dict[str, Any]
    film_box: dict[str, Any]
    rows: int
    cols: int
    images: list[tuple[int, Any]]      # (posição base 0, pixels uint8)
    film_box_uid: str
    color: bool


class PrintSession:
    """Estado de uma associação de impressão (uma Film Session por associação)."""

    def __init__(self, color_allowed: bool, on_print: Callable[[PrintedFilm], int | None],
                 printer_status: Callable[[], tuple[str, str]], honor_density: bool = False) -> None:
        self.color_allowed = color_allowed
        self.on_print = on_print
        self.printer_status = printer_status
        self.honor_density = honor_density
        self.session_uid: str | None = None
        self.session_attrs: dict[str, Any] = {}
        self.film_boxes: dict[str, FilmBox] = {}
        self.image_boxes: dict[str, ImageBox] = {}
        self.luts: dict[str, PresentationLut] = {}
        self.jobs: list[int] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ N-CREATE
    def n_create(self, sop_class: str, instance_uid: str | None, ds) -> tuple[int, Any]:
        from pydicom.dataset import Dataset
        with self._lock:
            if sop_class == FILM_SESSION:
                if self.session_uid is not None:
                    return DUPLICATE_INSTANCE, None
                self.session_uid = instance_uid or _uid()
                self.session_attrs = _attrs(ds, SESSION_KEYS)
                copies = self.session_attrs.get("NumberOfCopies", 1)
                try:
                    if not 1 <= int(copies) <= 99:
                        raise ValueError
                except (TypeError, ValueError):
                    self.session_uid = None
                    return INVALID_VALUE, None
                rsp = Dataset()
                if instance_uid is None:
                    rsp.AffectedSOPInstanceUID = self.session_uid
                for k, v in self.session_attrs.items():
                    setattr(rsp, k, v)
                return SUCCESS, rsp

            if sop_class == FILM_BOX:
                if self.session_uid is None:
                    return NO_SUCH_INSTANCE, None
                fmt = str(ds.get("ImageDisplayFormat", "") if ds is not None else "")
                m = FORMAT_RE.match(fmt)
                if not fmt:
                    return MISSING_ATTRIBUTE, None
                if not m:
                    return INVALID_VALUE, None
                cols, rows = int(m[1]), int(m[2])
                if not (1 <= cols <= 8 and 1 <= rows <= 8):
                    return INVALID_VALUE, None
                attrs = _attrs(ds, FILMBOX_KEYS)
                orient = str(attrs.get("FilmOrientation", "PORTRAIT")).upper()
                if orient not in ("PORTRAIT", "LANDSCAPE"):
                    return INVALID_VALUE, None
                uid = instance_uid or _uid()
                fb = FilmBox(uid=uid, rows=rows, cols=cols, attrs=attrs)
                ref_lut = ds.get("ReferencedPresentationLUTSequence") if ds is not None else None
                if ref_lut:
                    lut_uid = str(ref_lut[0].ReferencedSOPInstanceUID)
                    if lut_uid not in self.luts:
                        return NO_SUCH_INSTANCE, None
                    fb.presentation_lut = lut_uid
                color = self.color_allowed
                rsp = Dataset()
                if instance_uid is None:
                    rsp.AffectedSOPInstanceUID = uid
                for k, v in attrs.items():
                    setattr(rsp, k, v)
                ref_fs = Dataset()
                ref_fs.ReferencedSOPClassUID = FILM_SESSION
                ref_fs.ReferencedSOPInstanceUID = self.session_uid
                rsp.ReferencedFilmSessionSequence = [ref_fs]
                seq = []
                for pos in range(rows * cols):
                    ib = ImageBox(uid=_uid(), position=pos, film_box=uid, color=color)
                    self.image_boxes[ib.uid] = ib
                    fb.image_boxes.append(ib.uid)
                    item = Dataset()
                    item.ReferencedSOPClassUID = COLOR_IMAGE_BOX if color else GRAY_IMAGE_BOX
                    item.ReferencedSOPInstanceUID = ib.uid
                    seq.append(item)
                rsp.ReferencedImageBoxSequence = seq
                self.film_boxes[uid] = fb
                return SUCCESS, rsp

            if sop_class == PRESENTATION_LUT:
                uid = instance_uid or _uid()
                shape = str(ds.get("PresentationLUTShape", "") or "") if ds is not None else ""
                lut = PresentationLut(uid=uid, shape=shape.upper() or None)
                seq = ds.get("PresentationLUTSequence") if ds is not None else None
                if seq:
                    try:
                        lut.table = _explicit_lut(seq[0])
                    except Exception:  # noqa: BLE001
                        return INVALID_VALUE, None
                elif lut.shape not in ("IDENTITY", "LIN OD"):
                    return INVALID_VALUE, None
                self.luts[uid] = lut
                rsp = Dataset()
                if instance_uid is None:
                    rsp.AffectedSOPInstanceUID = uid
                return SUCCESS, rsp

            return NO_SUCH_SOP_CLASS, None

    # ------------------------------------------------------------------ N-SET
    def n_set(self, sop_class: str, instance_uid: str, ds) -> tuple[int, Any]:
        with self._lock:
            if sop_class in (GRAY_IMAGE_BOX, COLOR_IMAGE_BOX):
                ib = self.image_boxes.get(instance_uid)
                if ib is None:
                    return NO_SUCH_INSTANCE, None
                key = "BasicColorImageSequence" if sop_class == COLOR_IMAGE_BOX else "BasicGrayscaleImageSequence"
                seq = ds.get(key) if ds is not None else None
                if "ImageBoxPosition" in ds and int(ds.ImageBoxPosition) != ib.position + 1:
                    return INVALID_VALUE, None
                ib.polarity = str(ds.get("Polarity", ib.polarity) or "NORMAL").upper()
                ib.attrs.update(_attrs(ds, ("MagnificationType", "SmoothingType", "RequestedImageSize",
                                            "RequestedDecimateCropBehavior")))
                if seq:
                    try:
                        ib.pixels = _decode_image(seq[0], color=sop_class == COLOR_IMAGE_BOX)
                    except ValueError as exc:
                        log.warning("Image Box inválido: %s", exc)
                        return INVALID_VALUE, None
                    except MemoryError:
                        return FAIL_IMAGE_SIZE, None
                return SUCCESS, None
            if sop_class == FILM_BOX:
                fb = self.film_boxes.get(instance_uid)
                if fb is None:
                    return NO_SUCH_INSTANCE, None
                fb.attrs.update({k: v for k, v in _attrs(ds, FILMBOX_KEYS).items() if k != "ImageDisplayFormat"})
                return SUCCESS, None
            if sop_class == FILM_SESSION:
                if instance_uid != self.session_uid:
                    return NO_SUCH_INSTANCE, None
                self.session_attrs.update(_attrs(ds, SESSION_KEYS))
                return SUCCESS, None
            return NO_SUCH_SOP_CLASS, None

    # ------------------------------------------------------------------ N-ACTION
    def n_action(self, sop_class: str, instance_uid: str, action: int | None) -> tuple[int, Any]:
        if action != 1:
            return NO_SUCH_ACTION, None
        with self._lock:
            if sop_class == FILM_BOX:
                fb = self.film_boxes.get(instance_uid)
                if fb is None:
                    return NO_SUCH_INSTANCE, None
                boxes = [fb]
            elif sop_class == FILM_SESSION:
                if instance_uid != self.session_uid:
                    return NO_SUCH_INSTANCE, None
                boxes = list(self.film_boxes.values())
                if not boxes:
                    return WARN_EMPTY_SESSION, None
            else:
                return NO_SUCH_SOP_CLASS, None
            films = []
            for fb in boxes:
                imgs = [self.image_boxes[u] for u in fb.image_boxes]
                filled = [(ib.position, self._presented(ib, fb)) for ib in imgs if ib.pixels is not None]
                if not filled:
                    continue
                films.append(PrintedFilm(film_session=dict(self.session_attrs), film_box=dict(fb.attrs),
                                         rows=fb.rows, cols=fb.cols, images=filled, film_box_uid=fb.uid,
                                         color=any(ib.color for ib in imgs)))
                fb.printed = True
        if not films:
            return (WARN_EMPTY_FILMBOX if sop_class == FILM_BOX else WARN_EMPTY_SESSION), None
        try:
            for film in films:
                job = self.on_print(film)
                if job is not None:
                    self.jobs.append(job)
        except Exception:  # noqa: BLE001
            log.exception("Falha ao enfileirar impressão")
            return PROCESSING_FAILURE, None
        return SUCCESS, None

    def _presented(self, ib: ImageBox, fb: FilmBox):
        """Aplica a polaridade e a Presentation LUT referenciada (valores P → saída)."""
        import numpy as np
        px = ib.pixels
        lut = self.luts.get(fb.presentation_lut) if fb.presentation_lut else None
        if lut is not None and lut.table is not None and px.ndim == 2:
            idx = np.clip((px.astype(np.int32) * (len(lut.table) - 1)) // 255, 0, len(lut.table) - 1)
            px = (lut.table[idx] * 255.0 + 0.5).astype(np.uint8)
        if ib.polarity == "REVERSE":
            px = 255 - px
        return px

    # ------------------------------------------------------------------ N-DELETE / N-GET
    def n_delete(self, sop_class: str, instance_uid: str) -> int:
        with self._lock:
            if sop_class == FILM_SESSION and instance_uid == self.session_uid:
                self.session_uid, self.session_attrs = None, {}
                self.film_boxes.clear()
                self.image_boxes.clear()
                return SUCCESS
            if sop_class == FILM_BOX and instance_uid in self.film_boxes:
                fb = self.film_boxes.pop(instance_uid)
                for u in fb.image_boxes:
                    self.image_boxes.pop(u, None)
                return SUCCESS
            if sop_class == PRESENTATION_LUT and instance_uid in self.luts:
                del self.luts[instance_uid]
                return SUCCESS
            return NO_SUCH_INSTANCE

    def n_get_printer(self, instance_uid: str, product: str, version: str) -> tuple[int, Any]:
        from pydicom.dataset import Dataset
        if instance_uid != PRINTER_INSTANCE:
            return NO_SUCH_INSTANCE, None
        status, info = self.printer_status()
        ds = Dataset()
        ds.PrinterStatus = status              # NORMAL | WARNING | FAILURE
        ds.PrinterStatusInfo = info            # termos definidos PS3.3 C.13.9.1
        ds.PrinterName = product[:64]
        ds.Manufacturer = "VYONIX"
        ds.ManufacturerModelName = "DICOM Print"
        ds.SoftwareVersions = version
        return SUCCESS, ds

    @property
    def unprinted(self) -> int:
        return sum(1 for fb in self.film_boxes.values()
                   if not fb.printed and any(self.image_boxes[u].pixels is not None for u in fb.image_boxes))


def _decode_image(item, *, color: bool):
    """Converte o Image Pixel Module do Image Box em uint8 (valores de apresentação)."""
    import numpy as np
    for k in ("Rows", "Columns", "PixelData"):
        if k not in item:
            raise ValueError(f"{k} ausente")
    rows, cols = int(item.Rows), int(item.Columns)
    if rows < 1 or cols < 1 or rows * cols > 8192 * 8192:
        raise ValueError("dimensões inválidas")
    data = bytes(item.PixelData)
    if len(data) > MAX_IMAGE_BYTES:
        raise MemoryError
    if color:
        if int(item.get("SamplesPerPixel", 3)) != 3:
            raise ValueError("imagem colorida deve ter 3 amostras por pixel")
        need = rows * cols * 3
        if len(data) < need:
            raise ValueError("Pixel Data menor que o esperado")
        arr = np.frombuffer(data[:need], dtype=np.uint8)
        if int(item.get("PlanarConfiguration", 0)) == 1:
            return np.ascontiguousarray(arr.reshape(3, rows, cols).transpose(1, 2, 0))
        return arr.reshape(rows, cols, 3).copy()
    bits_alloc = int(item.get("BitsAllocated", 8))
    bits_stored = int(item.get("BitsStored", bits_alloc))
    photometric = str(item.get("PhotometricInterpretation", "MONOCHROME2")).upper()
    if bits_alloc == 8:
        need = rows * cols
        if len(data) < need:
            raise ValueError("Pixel Data menor que o esperado")
        arr = np.frombuffer(data[:need], dtype=np.uint8).reshape(rows, cols)
        out = arr.copy() if bits_stored >= 8 else (arr.astype(np.uint16) * 255 // (2 ** bits_stored - 1)).astype(np.uint8)
    elif bits_alloc == 16:
        need = rows * cols * 2
        if len(data) < need:
            raise ValueError("Pixel Data menor que o esperado")
        arr = np.frombuffer(data[:need], dtype="<u2").reshape(rows, cols) & ((1 << bits_stored) - 1)
        out = ((arr.astype(np.uint32) * 255 + (2 ** bits_stored - 1) // 2) // (2 ** bits_stored - 1)).astype(np.uint8)
    else:
        raise ValueError(f"Bits Allocated {bits_alloc} não suportado")
    if photometric == "MONOCHROME1":
        out = 255 - out
    elif photometric != "MONOCHROME2":
        raise ValueError(f"interpretação fotométrica {photometric} inválida para Image Box em tons de cinza")
    return out


def _explicit_lut(item):
    import numpy as np
    desc = [int(x) for x in item.LUTDescriptor]
    entries = desc[0] or 65536
    bits = desc[2]
    raw = item.LUTData
    if isinstance(raw, (bytes, bytearray)):
        data = np.frombuffer(raw, dtype="<u2" if bits > 8 else np.uint8)
    else:
        data = np.asarray(raw if isinstance(raw, (list, tuple)) else [raw], dtype=np.float64)
    data = np.asarray(data[:entries], dtype=np.float64)
    if len(data) < 2:
        raise ValueError("LUT explícita vazia")
    return np.clip(data / float(2 ** bits - 1), 0.0, 1.0)
