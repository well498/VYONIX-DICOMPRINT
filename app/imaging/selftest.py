"""Autoteste dos codecs de imagem (usado pelo ``--smoke-test`` e pelos testes).

Gera uma imagem sintética de 16 bits, comprime com cada codec sem perdas disponível, grava,
decodifica pelo mesmo caminho usado na impressão e confere que os pixels voltam idênticos.
Prova que os decodificadores funcionam dentro do executável empacotado.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.dicom import sop
from app.imaging import codecs


def _dataset(path: Path):
    import numpy as np
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.7"
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID, ds.SOPInstanceUID = meta.MediaStorageSOPClassUID, meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID, ds.SeriesInstanceUID = generate_uid(), generate_uid()
    ds.Modality = "OT"
    ds.Rows, ds.Columns = 32, 48
    ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
    ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 12, 11, 0
    arr = (np.arange(32 * 48, dtype=np.uint16).reshape(32, 48) * 7) % 4096
    ds.PixelData = arr.tobytes()
    return ds, arr


LOSSLESS = [(sop.RLE_LOSSLESS, None), (sop.JPEG_2000_LOSSLESS, "pylibjpeg"), (sop.JPEG_LS_LOSSLESS, "pyjpegls")]


def run() -> dict[str, str]:
    from app.imaging.decoder import decode_frame

    results: dict[str, str] = {}
    available = set(codecs.decodable_compressed())
    with tempfile.TemporaryDirectory(prefix="vyonix-codec-") as tmp:
        for ts, plugin in LOSSLESS:
            name = sop.TRANSFER_SYNTAX_NAMES[ts]
            if ts not in available:
                results[name] = "indisponível"
                continue
            path = Path(tmp) / f"{ts}.dcm"
            try:
                ds, arr = _dataset(path)
                kwargs = {"encoding_plugin": plugin} if plugin else {}
                ds.compress(ts, arr, **kwargs)
                ds.save_as(str(path), enforce_file_format=True)
                _, _, out = decode_frame(path)
                results[name] = "ok" if (out == arr).all() else "pixels diferentes"
            except Exception as exc:  # noqa: BLE001
                results[name] = f"falha: {type(exc).__name__}: {str(exc)[:120]}"
    return results
