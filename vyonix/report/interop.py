"""TELELAUDO T8 — saídas padronizadas **opcionais** do laudo liberado (nenhuma é obrigatória nem pressupõe suporte
do equipamento ou sistema de destino):

* **FHIR R4** ``DiagnosticReport`` (JSON), com o PDF em ``presentedForm`` e o estudo em ``imagingStudy`` (por
  identificador DICOM);
* **HL7 v2.5** ``ORU^R01`` (texto do laudo em OBX TX, caracteres delimitadores escapados);
* **DICOM Encapsulated PDF** (1.2.840.10008.5.1.4.1.1.104.1) no mesmo estudo, para guardar no PACS do VYONIX.

Os dados vêm das versões imutáveis e do cadastro; cada geração fica na auditoria (sem conteúdo clínico).
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from vyonix.audit import service as audit
from vyonix.errors import Conflict, NotFound
from vyonix.report.models import Physician, Report, ReportVersion

ENCAPSULATED_PDF = "1.2.840.10008.5.1.4.1.1.104.1"
LOINC_IMAGING = {"system": "http://loinc.org", "code": "18748-4", "display": "Diagnostic imaging study"}


def _data(s: Session, report_id: uuid.UUID) -> dict[str, Any]:
    from vyonix.clinical.models import Order, Patient, PatientIdentifier, Study
    r = s.get(Report, report_id)
    if r is None:
        raise NotFound("Laudo não encontrado.")
    if r.status != "final":
        raise Conflict("Só laudo liberado pode ser exportado.")
    st = s.get(Study, r.study_id)
    p = s.get(Patient, st.patient_id) if st and st.patient_id else None
    o = s.get(Order, r.order_id) if r.order_id else None
    ids = list(s.execute(select(PatientIdentifier).where(PatientIdentifier.patient_id == p.id)
                         .order_by(PatientIdentifier.issuer)).scalars()) if p else []
    vs = list(s.execute(select(ReportVersion).where(ReportVersion.report_id == r.id)
                        .order_by(ReportVersion.version)).scalars())
    signer = None
    if vs and vs[0].signed_by_id:
        signer = s.execute(select(Physician).where(Physician.user_id == vs[0].signed_by_id)).scalar_one_or_none()
    return {"report": r, "study": st, "patient": p, "order": o, "ids": ids, "versions": vs, "signer": signer}


def _text(vs: list[ReportVersion]) -> str:
    parts = []
    for v in vs:
        from vyonix.report import richtext
        txt = richtext.to_text(v.body, v.body_format or "text")
        parts.append(txt if v.kind == "final" else f"ADENDO ({v.signed_at.strftime('%d/%m/%Y %H:%M')}): {txt}")
    return "\n\n".join(parts)


def fhir(s: Session, report_id: uuid.UUID, *, pdf: bytes | None = None, actor: str, actor_id=None,
         ip=None) -> dict[str, Any]:
    d = _data(s, report_id)
    r, st, p, vs, signer = d["report"], d["study"], d["patient"], d["versions"], d["signer"]
    res: dict[str, Any] = {
        "resourceType": "DiagnosticReport", "id": str(r.id),
        "status": "amended" if len(vs) > 1 else "final",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0074", "code": "RAD",
                                  "display": "Radiology"}]}],
        "code": {"coding": [LOINC_IMAGING], "text": (st.description or st.modality or "Exame de imagem") if st else
                 "Exame de imagem"},
        "issued": vs[-1].signed_at.astimezone(timezone.utc).isoformat(),
        "conclusion": _text(vs),
        "identifier": [{"system": "urn:vyonix:report", "value": str(r.id)}],
    }
    if p is not None:
        res["subject"] = {"display": p.name,
                          "identifier": ({"system": f"urn:vyonix:issuer:{d['ids'][0].issuer}",
                                          "value": d["ids"][0].value} if d["ids"] else None)}
        if res["subject"]["identifier"] is None:
            del res["subject"]["identifier"]
    if st is not None:
        if st.study_date:
            res["effectiveDateTime"] = st.study_date.isoformat()
        res["imagingStudy"] = [{"identifier": {"system": "urn:dicom:uid", "value": f"urn:oid:{st.study_instance_uid}"},
                                "display": st.accession or st.study_instance_uid}]
        if st.accession:
            res["identifier"].append({"type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                                                           "code": "ACSN"}]}, "value": st.accession})
    if signer is not None:
        res["resultsInterpreter"] = [{"display": signer.full_name,
                                      "identifier": {"system": f"urn:br:crm:{signer.crm_uf}", "value": signer.crm}}]
    if pdf is not None:
        res["presentedForm"] = [{"contentType": "application/pdf", "language": "pt-BR",
                                 "data": base64.b64encode(pdf).decode(), "title": "Laudo"}]
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="report.export.fhir", target_type="report",
                 target_id=r.id, details={"versions": len(vs)})
    return res


def _h(v: Any) -> str:
    """Escape HL7 v2 (| ^ ~ \\ &) e quebras de linha."""
    t = "" if v is None else str(v)
    t = t.replace("\\", "\\E\\").replace("|", "\\F\\").replace("^", "\\S\\").replace("~", "\\R\\").replace("&", "\\T\\")
    return t.replace("\r", " ").replace("\n", " ")


def hl7_oru(s: Session, report_id: uuid.UUID, *, sending_app: str = "VYONIX", sending_facility: str = "",
            actor: str, actor_id=None, ip=None) -> str:
    d = _data(s, report_id)
    r, st, p, o, vs, signer = d["report"], d["study"], d["patient"], d["order"], d["versions"], d["signer"]
    now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    pid = d["ids"][0] if d["ids"] else None
    name = (p.name or "").split() if p else []
    pn = f"{_h(name[-1])}^{_h(' '.join(name[:-1]))}" if len(name) > 1 else _h(p.name if p else "")
    segs = [
        f"MSH|^~\\&|{_h(sending_app)}|{_h(sending_facility)}|||{now}||ORU^R01^ORU_R01|{str(r.id)[:20]}|P|2.5|||AL|NE||UNICODE UTF-8",
        f"PID|1||{_h(pid.value) + '^^^' + _h(pid.issuer) if pid else ''}||{pn}||"
        f"{p.birth_date.strftime('%Y%m%d') if p and p.birth_date else ''}|{_h(p.sex) if p and p.sex else ''}",
        f"OBR|1|{_h(o.accession) if o else ''}|{_h(st.accession) if st else ''}|"
        f"{LOINC_IMAGING['code']}^{_h(st.description or st.modality or 'Exame de imagem') if st else ''}^LN|||"
        f"{st.study_date.strftime('%Y%m%d') if st and st.study_date else ''}|||||||||||||||"
        f"{vs[-1].signed_at.strftime('%Y%m%d%H%M%S')}||{_h(st.modality) if st else ''}|{'C' if len(vs) > 1 else 'F'}"
        f"|||||||{_h(signer.crm) + '&' + _h(signer.full_name) if signer else ''}",          # OBR-32 intérprete
    ]
    for i, line in enumerate(_text(vs).splitlines() or [""], start=1):
        segs.append(f"OBX|{i}|TX|{LOINC_IMAGING['code']}^Laudo^LN||{_h(line)}||||||{'C' if len(vs) > 1 else 'F'}")
    if st is not None:
        segs.append(f"OBX|{len(segs) - 2}|ST|113014^Study Instance UID^DCM||{_h(st.study_instance_uid)}||||||F")
    audit.record(s, actor=actor, actor_id=actor_id, ip=ip, action="report.export.hl7", target_type="report",
                 target_id=r.id, details={"segments": len(segs)})
    return "\r".join(segs) + "\r"


def dicom_pdf(s: Session, report_id: uuid.UUID, pdf: bytes, *, patient_id: str | None = None) -> bytes:
    """Encapsulated PDF no mesmo estudo (série nova, UIDs 2.25), com os dados do paciente do cadastro."""
    import io as _io
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid
    d = _data(s, report_id)
    r, st, p, vs, signer = d["report"], d["study"], d["patient"], d["versions"], d["signer"]
    if st is None:
        raise Conflict("Laudo sem estudo.")
    sop = generate_uid(prefix=None)
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID, meta.MediaStorageSOPInstanceUID = ENCAPSULATED_PDF, sop
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SpecificCharacterSet = "ISO_IR 192"
    ds.SOPClassUID, ds.SOPInstanceUID = ENCAPSULATED_PDF, sop
    ds.StudyInstanceUID, ds.SeriesInstanceUID = st.study_instance_uid, generate_uid(prefix=None)
    ds.Modality, ds.SeriesNumber, ds.InstanceNumber = "DOC", 999, 1
    ds.SeriesDescription = "Laudo (VYONIX REPORT)"
    name = (p.name or "").split() if p else []
    ds.PatientName = f"{name[-1]}^{' '.join(name[:-1])}" if len(name) > 1 else (p.name if p else "")
    ds.PatientID = patient_id or (d["ids"][0].value if d["ids"] else "")
    ds.PatientBirthDate = p.birth_date.strftime("%Y%m%d") if p and p.birth_date else ""
    ds.PatientSex = p.sex if p and p.sex in ("M", "F", "O") else ""
    ds.AccessionNumber = st.accession or ""
    ds.StudyDate = st.study_date.strftime("%Y%m%d") if st.study_date else ""
    signed = vs[-1].signed_at.astimezone(timezone.utc)
    ds.ContentDate, ds.ContentTime = signed.strftime("%Y%m%d"), signed.strftime("%H%M%S")
    ds.AcquisitionDateTime = signed.strftime("%Y%m%d%H%M%S")
    ds.BurnedInAnnotation = "YES"
    ds.DocumentTitle = "Laudo"
    ds.ConceptNameCodeSequence = []
    ds.MIMETypeOfEncapsulatedDocument = "application/pdf"
    ds.EncapsulatedDocument = pdf + (b"\0" if len(pdf) % 2 else b"")
    ds.EncapsulatedDocumentLength = len(pdf)
    buf = _io.BytesIO()
    ds.save_as(buf, enforce_file_format=True)
    return buf.getvalue()
