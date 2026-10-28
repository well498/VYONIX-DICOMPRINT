"""Homologação interna: simulador de modalidade que envia um estudo **sintético** ao PACS local por DICOM (C-STORE),
pelo mesmo caminho de um equipamento real (motor DICOM → sincronização → índice → Central de Exames).

Só gera dados fictícios (imagens em degradê, comentário "DADOS SINTÉTICOS") e só envia para o computador local
(127.0.0.1). Disponível no instalador de homologação; na compilação comercial exige ``--forcar-teste``.
"""

from __future__ import annotations

import io
from datetime import datetime

from vyonix import build_flavor

ROOT = "2.25."
CT = "1.2.840.10008.5.1.4.1.1.2"


def _uid() -> str:
    import uuid
    return ROOT + str(uuid.uuid4().int)


def synthetic_study(*, patient_id: str, patient_name: str, issuer: str = "PRONTUARIO", accession: str = "",
                    modality: str = "CT", description: str = "Estudo sintético de homologação", images: int = 8,
                    station: str = "SIMULADOR_HML", size: int = 128) -> list:
    """Datasets pydicom de um estudo fictício (uma série, ``images`` imagens 16 bits)."""
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian
    study, series, now = _uid(), _uid(), datetime.now()
    family, _, given = patient_name.strip().partition(" ")
    out = []
    for n in range(1, images + 1):
        sop = _uid()
        meta = FileMetaDataset()
        meta.MediaStorageSOPClassUID, meta.MediaStorageSOPInstanceUID = CT, sop
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds = Dataset()
        ds.file_meta = meta
        ds.SOPClassUID, ds.SOPInstanceUID, ds.StudyInstanceUID, ds.SeriesInstanceUID = CT, sop, study, series
        ds.PatientID, ds.IssuerOfPatientID = patient_id, issuer
        ds.PatientName = f"{given}^{family}" if given else family          # Família^Nome a partir de "Nome Sobrenome"
        ds.PatientBirthDate, ds.PatientSex = "19800101", "O"
        ds.PatientComments = "DADOS SINTETICOS - HOMOLOGACAO VYONIX"
        ds.StudyDate, ds.StudyTime = now.strftime("%Y%m%d"), now.strftime("%H%M%S")
        ds.AccessionNumber, ds.StudyDescription, ds.StudyID = accession, description, "1"
        ds.Modality, ds.StationName, ds.Manufacturer = modality, station, "VYONIX SIMULADOR"
        ds.SeriesNumber, ds.InstanceNumber, ds.SeriesDescription = 1, n, "Série sintética"
        ds.Rows = ds.Columns = size
        ds.PixelSpacing, ds.SliceThickness = ["0.5", "0.5"], "5"
        ds.ImagePositionPatient, ds.ImageOrientationPatient = ["0", "0", str(n * 5)], ["1", "0", "0", "0", "1", "0"]
        ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
        ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 12, 11, 0
        ds.WindowCenter, ds.WindowWidth = "2048", "4096"
        px = bytearray()
        c = size / 2
        for y in range(size):
            for x in range(size):
                r = ((x - c) ** 2 + (y - c) ** 2) ** 0.5
                v = int(3000 * (1 - min(r / c, 1)) + 600 * ((x + y + n * 6) % 32 < 16) + n * 40)
                px += (min(v, 4095)).to_bytes(2, "little")
        ds.PixelData = bytes(px)
        ds["PixelData"].VR = "OW"
        out.append(ds)
    return out


def send(datasets: list, *, host: str = "127.0.0.1", port: int = 4242, called_ae: str = "VYONIX_PACS",
         calling_ae: str = "VYX_SIMULADOR") -> dict:
    from pynetdicom import AE
    from pynetdicom.sop_class import Verification
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("O simulador envia só para o computador local (127.0.0.1).")
    ae = AE(ae_title=calling_ae)
    ae.add_requested_context(CT)
    ae.add_requested_context(Verification)
    a = ae.associate(host, port, ae_title=called_ae)
    if not a.is_established:
        raise ConnectionError(f"O PACS local não aceitou a conexão em {host}:{port} (AE {called_ae}). "
                              "Confira se o módulo PACS foi ativado e o serviço VyonixPacsEngine está em execução.")
    ok = failed = 0
    try:
        for ds in datasets:
            st = a.send_c_store(ds)
            if st and st.Status == 0x0000:
                ok += 1
            else:
                failed += 1
    finally:
        a.release()
    return {"study_instance_uid": str(datasets[0].StudyInstanceUID) if datasets else None, "sent": ok, "failed": failed}


def allowed(force: bool) -> bool:
    return build_flavor.HOMOLOG or force


def to_bytes(ds) -> bytes:
    buf = io.BytesIO()
    ds.save_as(buf, enforce_file_format=True)
    return buf.getvalue()
