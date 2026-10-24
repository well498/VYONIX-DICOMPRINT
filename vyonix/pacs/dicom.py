"""Leitura, validação e representação DICOM JSON (PS3.18, anexo F) para o PACS.

Nenhuma alteração é feita no objeto DICOM recebido: o arquivo é guardado como chegou. A validação
recusa o que não pode ser indexado com segurança (sem UIDs, UIDs inválidos, sem identificação do
paciente) e registra o SHA-256 do conteúdo para conferência de integridade.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

UID_RE = re.compile(r"^[0-9]+(\.[0-9]+)*$")
MAX_INSTANCE_BYTES = 2 * 1024 * 1024 * 1024           # 2 GB por instância

# Atributos devolvidos pelo QIDO-RS (PS3.18, tabela 10.6.1-5 e seguintes) — subconjunto usado pelo OHIF.
STUDY_TAGS = ("00080020", "00080030", "00080050", "00080061", "00080090", "00081030", "00100010", "00100020",
              "00100030", "00100040", "0020000D", "00200010", "00201206", "00201208")
SERIES_TAGS = ("00080060", "0008103E", "0020000E", "00200011", "00201209", "0020000D")
INSTANCE_TAGS = ("00080016", "00080018", "00200013", "00280010", "00280011", "00280008", "0020000E", "0020000D")


class DicomRejected(ValueError):
    """Objeto recusado na entrada (motivo legível em português)."""


@dataclass(frozen=True)
class ParsedInstance:
    study_uid: str
    series_uid: str
    sop_uid: str
    sop_class_uid: str
    transfer_syntax: str
    patient_id: str
    patient_name: str
    patient_birth_date: date | None
    patient_sex: str | None
    study_date: date | None
    study_time: str | None
    accession: str | None
    study_description: str | None
    referring_physician: str | None
    study_id: str | None
    modality: str | None
    series_number: int | None
    series_description: str | None
    instance_number: int | None
    rows: int | None
    columns: int | None
    frames: int
    has_pixels: bool
    sha256: str
    size: int
    extra: dict[str, Any] = field(default_factory=dict)


def _s(v) -> str | None:
    if v is None:
        return None
    t = str(v).strip()
    return t or None


def _i(v) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _d(v) -> date | None:
    t = _s(v)
    if not t or len(t) < 8 or not t[:8].isdigit():
        return None
    try:
        return date(int(t[:4]), int(t[4:6]), int(t[6:8]))
    except ValueError:
        return None


def parse(data: bytes) -> tuple[ParsedInstance, Any]:
    """Valida e extrai os identificadores de um arquivo DICOM Part 10. Retorna (dados, dataset)."""
    import pydicom
    from pydicom.errors import InvalidDicomError
    if not data:
        raise DicomRejected("Arquivo vazio.")
    if len(data) > MAX_INSTANCE_BYTES:
        raise DicomRejected("Instância acima do tamanho máximo aceito (2 GB).")
    try:
        ds = pydicom.dcmread(io.BytesIO(data), force=False)
    except InvalidDicomError as exc:
        raise DicomRejected("O arquivo não é DICOM (falta o cabeçalho Part 10).") from exc
    except Exception as exc:  # noqa: BLE001 - arquivo truncado ou corrompido
        raise DicomRejected(f"Arquivo DICOM corrompido ou incompleto: {exc}") from exc
    meta = getattr(ds, "file_meta", None)
    uids = {"Study Instance UID": _s(ds.get("StudyInstanceUID")), "Series Instance UID": _s(ds.get("SeriesInstanceUID")),
            "SOP Instance UID": _s(ds.get("SOPInstanceUID")), "SOP Class UID": _s(ds.get("SOPClassUID"))}
    for label, v in uids.items():
        if not v:
            raise DicomRejected(f"{label} ausente.")
        if len(v) > 64 or not UID_RE.match(v):
            raise DicomRejected(f"{label} inválido.")
    if uids["Study Instance UID"] == uids["Series Instance UID"] or uids["Series Instance UID"] == uids["SOP Instance UID"]:
        raise DicomRejected("UIDs repetidos entre estudo, série e instância.")
    patient_id = _s(ds.get("PatientID"))
    if not patient_id:
        raise DicomRejected("Patient ID ausente: o estudo não pode ser associado a um paciente com segurança.")
    has_pixels = "PixelData" in ds
    sex = _s(ds.get("PatientSex"))
    p = ParsedInstance(
        study_uid=uids["Study Instance UID"], series_uid=uids["Series Instance UID"], sop_uid=uids["SOP Instance UID"],
        sop_class_uid=uids["SOP Class UID"],
        transfer_syntax=_s(getattr(meta, "TransferSyntaxUID", None)) or "1.2.840.10008.1.2",
        patient_id=patient_id[:64], patient_name=(_s(ds.get("PatientName")) or "")[:200],
        patient_birth_date=_d(ds.get("PatientBirthDate")), patient_sex=sex if sex in ("M", "F", "O") else None,
        study_date=_d(ds.get("StudyDate")), study_time=_s(ds.get("StudyTime")),
        accession=(_s(ds.get("AccessionNumber")) or None), study_description=_s(ds.get("StudyDescription")),
        referring_physician=_s(ds.get("ReferringPhysicianName")), study_id=_s(ds.get("StudyID")),
        modality=_s(ds.get("Modality")), series_number=_i(ds.get("SeriesNumber")),
        series_description=_s(ds.get("SeriesDescription")), instance_number=_i(ds.get("InstanceNumber")),
        rows=_i(ds.get("Rows")), columns=_i(ds.get("Columns")), frames=_i(ds.get("NumberOfFrames")) or (1 if has_pixels else 0),
        has_pixels=has_pixels, sha256=hashlib.sha256(data).hexdigest(), size=len(data))
    return p, ds


def instance_json(ds) -> dict[str, Any]:
    """Metadados WADO-RS (DICOM JSON) sem os dados de pixel nem outros dados volumosos (só o VR deles)."""
    return _to_json(ds, lambda _tag, vr: {"vr": vr})


def _to_json(ds, bulk) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for el in ds:
        tag = f"{el.tag.group:04X}{el.tag.element:04X}"
        if el.tag.group == 0x7FE0 or el.VR in ("OB", "OW", "OF", "OD", "OL", "OV", "UN"):
            out[tag] = bulk(tag, el.VR)
            continue
        try:
            out[tag] = el.to_json_dict(bulk_data_element_handler=None, bulk_data_threshold=1024 * 64)
        except Exception:  # noqa: BLE001 - elemento malformado: só o VR
            out[tag] = {"vr": el.VR}
    return out


def _pn(name: str | None) -> list[dict] | None:
    return [{"Alphabetic": name}] if name else None


def _attr(vr: str, value) -> dict[str, Any]:
    if value is None or value == [] or value == "":
        return {"vr": vr}
    return {"vr": vr, "Value": value if isinstance(value, list) else [value]}


def study_json(st, modalities: list[str], n_series: int, n_instances: int) -> dict[str, Any]:
    return {
        "00080020": _attr("DA", st.study_date.strftime("%Y%m%d") if st.study_date else None),
        "00080030": _attr("TM", st.study_time),
        "00080050": _attr("SH", st.accession),
        "00080061": _attr("CS", sorted(m for m in modalities if m)),
        "00080090": {"vr": "PN", **({"Value": _pn(st.referring_physician)} if st.referring_physician else {})},
        "00081030": _attr("LO", st.description),
        "00100010": {"vr": "PN", **({"Value": _pn(st.patient_name)} if st.patient_name else {})},
        "00100020": _attr("LO", st.patient_id),
        "00100030": _attr("DA", st.patient_birth_date.strftime("%Y%m%d") if st.patient_birth_date else None),
        "00100040": _attr("CS", st.patient_sex),
        "0020000D": _attr("UI", st.study_uid),
        "00200010": _attr("SH", st.dicom_study_id),
        "00201206": _attr("IS", n_series),
        "00201208": _attr("IS", n_instances),
    }


def series_json(se, study_uid: str, n_instances: int) -> dict[str, Any]:
    return {
        "00080060": _attr("CS", se.modality),
        "0008103E": _attr("LO", se.description),
        "0020000D": _attr("UI", study_uid),
        "0020000E": _attr("UI", se.series_uid),
        "00200011": _attr("IS", se.series_number),
        "00201209": _attr("IS", n_instances),
    }


def instance_summary_json(it, study_uid: str, series_uid: str) -> dict[str, Any]:
    return {
        "00080016": _attr("UI", it.sop_class_uid),
        "00080018": _attr("UI", it.sop_uid),
        "0020000D": _attr("UI", study_uid),
        "0020000E": _attr("UI", series_uid),
        "00200013": _attr("IS", it.instance_number),
        "00280008": _attr("IS", it.frames if it.frames and it.frames > 1 else None),
        "00280010": _attr("US", it.rows),
        "00280011": _attr("US", it.columns),
    }
