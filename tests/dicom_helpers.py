"""Geração de arquivos DICOM sintéticos para testes (sem dados de pacientes reais)."""

from __future__ import annotations

import socket
from pathlib import Path


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_ct(path: Path, *, sop_uid: str | None = None, study_uid: str = "1.2.826.0.1.3680043.8.498.1",
            series_uid: str = "1.2.826.0.1.3680043.8.498.1.1", rows: int = 8, cols: int = 8,
            value: int = 1000, modality: str = "CT", sop_class: str = "1.2.840.10008.5.1.4.1.1.2",
            patient_name: str = "TESTE^SINTETICO") -> Path:
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    sop_uid = sop_uid or generate_uid(prefix="1.2.826.0.1.3680043.8.498.")
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = sop_class
    meta.MediaStorageSOPInstanceUID = sop_uid
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = sop_class
    ds.SOPInstanceUID = sop_uid
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.Modality = modality
    ds.PatientName = patient_name
    ds.PatientID = "SINT-0001"
    ds.Rows, ds.Columns = rows, cols
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 12
    ds.HighBit = 11
    ds.PixelRepresentation = 0
    ds.RescaleSlope = 1
    ds.RescaleIntercept = -1024
    ds.WindowCenter = 40
    ds.WindowWidth = 400
    ds.PixelData = int(value).to_bytes(2, "little") * (rows * cols)
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(str(path), enforce_file_format=True)
    return path
