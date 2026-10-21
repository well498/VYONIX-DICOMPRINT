"""Converte um filme impresso via DICOM Print (N-ACTION) em trabalho da fila.

Cada Image Box preenchido vira uma instância de Captura Secundária (8 bits, valores de
apresentação já prontos, janela identidade) gravada pelo mesmo ``InstanceStore`` do Storage
SCP — com gravação atômica, retenção e rastreabilidade. O trabalho guarda as posições originais
(células vazias continuam vazias) e as configurações vindas do pedido DICOM, com essa origem
registrada. O tamanho de filme pedido só vira papel quando é um papel (A4/A3); filmes como
14INX17IN usam o papel do perfil/padrão, e isso fica anotado no trabalho.
"""

from __future__ import annotations

import io
from typing import Any, Callable

from app.core.contracts import AssociationPeer
from app.dicom.print_model import PrintedFilm
from app.dicom.storage import InstanceStore
from app.jobs.service import JobService
from app.printing.paper import FILM_SIZES
from app.utils.logging_setup import get_logger

log = get_logger("dicom.print_intake")

SECONDARY_CAPTURE = "1.2.840.10008.5.1.4.1.1.7"


def _sc_dataset(pixels, study_uid: str, series_uid: str, number: int, ae: str) -> bytes:
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    sop_uid = generate_uid(prefix="1.2.826.0.1.3680043.8.498.")
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = SECONDARY_CAPTURE
    meta.MediaStorageSOPInstanceUID = sop_uid
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID, ds.SOPInstanceUID = SECONDARY_CAPTURE, sop_uid
    ds.StudyInstanceUID, ds.SeriesInstanceUID = study_uid, series_uid
    ds.Modality = "OT"
    ds.ConversionType = "WSD"
    ds.InstanceNumber = number
    ds.PatientName, ds.PatientID = "", ""        # o DICOM Print não transmite dados do paciente
    ds.SeriesDescription = f"DICOM Print de {ae}"[:64]
    ds.Rows, ds.Columns = int(pixels.shape[0]), int(pixels.shape[1])
    ds.BitsAllocated = ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    if pixels.ndim == 3:
        ds.SamplesPerPixel, ds.PhotometricInterpretation, ds.PlanarConfiguration = 3, "RGB", 0
    else:
        ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
        # Janela identidade: os valores já são de apresentação (P-values).
        ds.WindowCenter, ds.WindowWidth, ds.VOILUTFunction = 127.5, 255, "LINEAR_EXACT"
    ds.PixelData = pixels.tobytes()
    buf = io.BytesIO()
    ds.save_as(buf, enforce_file_format=True)
    return buf.getvalue()


class PrintIntake:
    def __init__(self, *, store: InstanceStore, jobs: JobService, settings_get: Callable[[str], Any],
                 device_modality: Callable[[int], str | None]) -> None:
        self.store = store
        self.jobs = jobs
        self.get = settings_get
        self.device_modality = device_modality

    def submit(self, film: PrintedFilm, *, peer: AssociationPeer, device_id: int | None, study_uid: str) -> int:
        from pydicom.uid import generate_uid
        series_uid = generate_uid(prefix="1.2.826.0.1.3680043.8.498.")
        items = []
        for n, (pos, px) in enumerate(sorted(film.images, key=lambda x: x[0]), start=1):
            encoded = _sc_dataset(px, study_uid, series_uid, n, peer.calling_ae)
            outcome = self.store.store(encoded, peer, device_id, max_bytes=len(encoded) + 1,
                                       retention_days=int(self.get("retention.images_days")), source="dicom_print")
            if outcome.instance is None:
                raise RuntimeError(f"falha ao gravar a imagem do Image Box {pos + 1}: {outcome.message}")
            row = self.store.db.connection().execute("SELECT id FROM instances WHERE sop_instance_uid = ?",
                                                     (outcome.instance.sop_instance_uid,)).fetchone()
            items.append((int(row["id"]), 0, pos))

        fb, fs = film.film_box, film.film_session
        overrides: dict[str, Any] = {"layout": f"{film.rows}x{film.cols}", "keep_positions": True,
                                     "orientation": str(fb.get("FilmOrientation", "PORTRAIT")).lower()}
        notes = []
        try:
            overrides["copies"] = max(1, min(99, int(fs.get("NumberOfCopies", 1))))
        except (TypeError, ValueError):
            pass
        film_size = str(fb.get("FilmSizeID", "") or "").upper()
        if film_size in ("A4", "A3"):
            overrides["paper"] = film_size
        elif film_size:
            known = "conhecido" if film_size in FILM_SIZES else "desconhecido"
            notes.append(f"Filme {film_size} ({known}) pedido; usado o papel do perfil/padrão")
        if str(fb.get("Trim", "")).upper() == "YES":
            overrides["border"] = True
        if self.get("dicom.print.honor_density"):
            empty = str(fb.get("EmptyImageDensity", "") or "").upper()
            if empty in ("BLACK", "WHITE"):
                overrides["background"] = 0 if empty == "BLACK" else 255
        elif fb.get("BorderDensity") or fb.get("EmptyImageDensity"):
            notes.append("Densidades de borda/fundo do filme registradas, não aplicadas ao papel")
        for k in ("MagnificationType", "MinDensity", "MaxDensity"):
            if k in fb:
                notes.append(f"{k}={fb[k]} recebido")
        modality = self.device_modality(device_id) if device_id else None
        priority = {"HIGH": 10, "MED": 0, "LOW": -10}.get(str(fs.get("PrintPriority", "MED")).upper(), 0)
        job_id, _ = self.jobs.create(
            source_type="dicom_print", items=items, idempotency_key=f"dicom_print:{film.film_box_uid}",
            device_id=device_id, source_ae=peer.calling_ae, modality=modality, dicom=overrides,
            priority=priority,
            rule_facts={"film_size": film_size or None, "display_format": f"{film.cols},{film.rows}"},
            reason="; ".join(notes) if notes else None)
        log.info("Filme recebido por DICOM Print", extra={"job": job_id, "images": len(items),
                                                          "format": f"{film.rows}x{film.cols}"})
        return job_id
