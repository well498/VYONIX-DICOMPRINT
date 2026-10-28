"""Apoio aos testes do PACS: objetos DICOM sintéticos e um motor de armazenamento DUBLÊ DE TESTE.

``MemoryBackend`` NÃO é usado em produção e não substitui o Orthanc: ele existe só para os testes de
unidade do índice, da validação e do isolamento rodarem sem o motor. Ele reproduz o comportamento do
Orthanc que importa para o CORE (identificador derivado dos UIDs, ``AlreadyStored`` sem sobrescrever,
``/changes``). A integração com o Orthanc real é testada em ``test_pacs_orthanc.py``.

Os objetos DICOM são sintéticos (sem pacientes reais): nomes e identificadores inventados.
"""

from __future__ import annotations

import hashlib
import io

from vyonix.pacs.backend import BackendUnavailable, Change, StoredRef

CT = "1.2.840.10008.5.1.4.1.1.2"
SC = "1.2.840.10008.5.1.4.1.1.7"
ROOT_UID = "1.2.826.0.1.3680043.10.1351"        # raiz sintética de testes


def uid(*parts: int) -> str:
    return ".".join([ROOT_UID, *map(str, parts)])


def make_dicom(*, study: str = uid(1), series: str = uid(1, 1), sop: str = uid(1, 1, 1), patient_id: str = "PAC-0001",
               patient_name: str = "TESTE^SINTETICO", modality: str = "CT", study_date: str = "20261020",
               accession: str = "", rows: int = 4, cols: int = 4, frames: int = 1, fill: int = 0,
               sop_class: str = CT, issuer: str = "", encapsulated: list[bytes] | None = None,
               instance_number: int = 1, series_number: int = 1, description: str = "Estudo sintético",
               pixel_spacing: tuple[float, float] | None = None, station: str | None = None) -> bytes:
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, JPEGBaseline8Bit
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = sop_class
    meta.MediaStorageSOPInstanceUID = sop
    meta.TransferSyntaxUID = JPEGBaseline8Bit if encapsulated else ExplicitVRLittleEndian
    meta.ImplementationClassUID = uid(999)
    ds = Dataset()
    ds.file_meta = meta
    ds.SOPClassUID, ds.SOPInstanceUID = sop_class, sop
    ds.StudyInstanceUID, ds.SeriesInstanceUID = study, series
    ds.PatientID, ds.PatientName = patient_id, patient_name
    if issuer:
        ds.IssuerOfPatientID = issuer
    ds.PatientBirthDate, ds.PatientSex = "19800101", "F"
    ds.StudyDate, ds.StudyTime, ds.AccessionNumber = study_date, "101500", accession
    ds.StudyDescription, ds.StudyID = description, "1"
    ds.ReferringPhysicianName = "MEDICO^SINTETICO"
    ds.Modality, ds.SeriesNumber, ds.InstanceNumber = modality, series_number, instance_number
    if station:
        ds.StationName = station
    ds.SeriesDescription = "Série sintética"
    ds.Rows, ds.Columns = rows, cols
    if pixel_spacing:
        ds.PixelSpacing = [str(v) for v in pixel_spacing]
    ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
    if encapsulated:
        from pydicom.encaps import encapsulate
        ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 8, 8, 7, 0
        ds.NumberOfFrames = len(encapsulated)
        ds.PixelData = encapsulate(encapsulated)
        ds["PixelData"].VR = "OB"
    else:
        ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 12, 11, 0
        if frames > 1:
            ds.NumberOfFrames = frames
        px = bytearray()
        for f in range(frames):
            for i in range(rows * cols):
                px += ((fill + f * 100 + i) & 0x0FFF).to_bytes(2, "little")
        ds.PixelData = bytes(px)
        ds["PixelData"].VR = "OW"
    buf = io.BytesIO()
    ds.save_as(buf, enforce_file_format=True)
    return buf.getvalue()


class MemoryBackend:
    """DUBLÊ DE TESTE do motor (ver docstring do módulo). Nunca usado fora dos testes."""
    name = "memoria-teste"

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.log: list[Change] = []
        self.down = False
        self.deleted: list[str] = []
        self.meta: dict[str, dict] = {}

    @staticmethod
    def _id(data: bytes) -> tuple[str, str]:
        import pydicom
        ds = pydicom.dcmread(io.BytesIO(data), stop_before_pixels=True)
        key = "|".join([str(ds.PatientID), str(ds.StudyInstanceUID), str(ds.SeriesInstanceUID),
                        str(ds.SOPInstanceUID)])
        return hashlib.sha1(key.encode()).hexdigest(), str(ds.SOPInstanceUID)

    def _check(self):
        if self.down:
            raise BackendUnavailable("motor de teste fora do ar")

    def ping(self) -> dict:
        self._check()
        return {"name": "memoria-teste", "version": "0"}

    def store(self, data: bytes) -> StoredRef:
        self._check()
        bid, sop = self._id(data)
        if bid in self.files:
            return StoredRef(bid, sop, already_existed=True)      # como o Orthanc: não sobrescreve
        self.files[bid] = data
        self.log.append(Change(len(self.log) + 1, bid))
        return StoredRef(bid, sop)

    def receive_cstore(self, data: bytes, called_aet: str = "VYONIX_PACS", remote_aet: str = "MODALIDADE") -> str:
        """Simula a chegada por C-STORE direto no motor (vai para ``changes``), com a origem registrada."""
        bid = self.store(data).backend_id
        self.meta[bid] = {"origin": "DicomProtocol", "called_aet": called_aet, "remote_aet": remote_aet,
                          "remote_ip": "127.0.0.1"}
        return bid

    def origin(self, backend_id: str) -> dict:
        self._check()
        if backend_id not in self.files:
            raise FileNotFoundError(backend_id)
        return self.meta.get(backend_id, {"origin": "RestApi", "called_aet": None, "remote_aet": None,
                                          "remote_ip": None})

    def fetch(self, backend_id: str) -> bytes:
        self._check()
        if backend_id not in self.files:
            raise FileNotFoundError(backend_id)
        return self.files[backend_id]

    def changes(self, since: int, limit: int = 100):
        self._check()
        out = [c for c in self.log if c.seq > since][:limit]
        last = out[-1].seq if out else since
        return out, last, last >= len(self.log)

    def delete(self, backend_id: str) -> None:
        self.deleted.append(backend_id)
        self.files.pop(backend_id, None)
