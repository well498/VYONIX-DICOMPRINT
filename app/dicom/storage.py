"""Persistência segura das instâncias recebidas (§4.1 itens 14–16; §6 item 22).

* O arquivo recebido é gravado primeiro em ``temp/``, sincronizado com o disco (``fsync``) e só
  então movido atomicamente para ``storage/<Study>/<Series>/<SOP>.dcm``. Uma queda no meio da
  gravação nunca deixa um arquivo parcial no armazenamento.
* O original nunca é alterado depois de gravado.
* UIDs são validados antes de virarem nomes de pasta (sem caracteres de caminho).
* Duplicatas são detectadas pelo SOP Instance UID: conteúdo idêntico é descartado sem erro;
  conteúdo diferente com o mesmo UID mantém o original e é registrado como conflito.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.contracts import AssociationPeer, ReceivedInstance
from app.database.connection import Database
from app.utils.logging_setup import get_logger
from app.utils.timeutil import to_iso, utc_now

log = get_logger("dicom.storage")

UID_RE = re.compile(r"^[0-9]+(\.[0-9]+)*$")

# Status DIMSE C-STORE (PS3.4 Annex B, PS3.7)
STATUS_SUCCESS = 0x0000
STATUS_OUT_OF_RESOURCES = 0xA700
STATUS_DATASET_MISMATCH = 0xA900
STATUS_CANNOT_UNDERSTAND = 0xC000
STATUS_PROCESSING_FAILURE = 0x0110


@dataclass(frozen=True)
class StoreOutcome:
    status: int
    message: str
    instance: ReceivedInstance | None = None
    duplicate: bool = False
    conflict: bool = False


def valid_uid(value: object) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 64 and bool(UID_RE.match(value))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class InstanceStore:
    def __init__(self, db: Database, storage_dir: Path, temp_dir: Path) -> None:
        # Ouvintes chamados após gravar uma instância nova: (instância, cabeçalho DICOM, origem).
        self.listeners: list = []
        self.db = db
        self.storage_dir = storage_dir
        self.temp_dir = temp_dir

    def path_for(self, study: str, series: str, sop: str) -> Path:
        return self.storage_dir / study / series / f"{sop}.dcm"

    def store(self, encoded: bytes, peer: AssociationPeer, device_id: int | None, *,
              max_bytes: int, retention_days: int | None = None, source: str = "storage") -> StoreOutcome:
        from pydicom import dcmread
        from pydicom.errors import InvalidDicomError

        if len(encoded) > max_bytes:
            return StoreOutcome(STATUS_OUT_OF_RESOURCES,
                                f"Instância de {len(encoded) / 1048576:.1f} MB excede o limite "
                                f"de {max_bytes / 1048576:.0f} MB")
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix="rx-", suffix=".dcm", dir=self.temp_dir)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(encoded)
                fh.flush()
                os.fsync(fh.fileno())
            try:
                ds = dcmread(tmp, stop_before_pixels=True)
            except (InvalidDicomError, ValueError, EOFError, OSError) as exc:
                return self._discard(tmp, StoreOutcome(STATUS_CANNOT_UNDERSTAND,
                                                       f"Arquivo DICOM inválido: {type(exc).__name__}"))
            meta = getattr(ds, "file_meta", None)
            sop = str(ds.get("SOPInstanceUID", "") or (meta.get("MediaStorageSOPInstanceUID", "") if meta else ""))
            sop_class = str(ds.get("SOPClassUID", "") or (meta.get("MediaStorageSOPClassUID", "") if meta else ""))
            study = str(ds.get("StudyInstanceUID", ""))
            series = str(ds.get("SeriesInstanceUID", ""))
            ts = str(meta.get("TransferSyntaxUID", "")) if meta else ""
            missing = [n for n, val in (("SOPInstanceUID", sop), ("SOPClassUID", sop_class),
                                        ("StudyInstanceUID", study), ("SeriesInstanceUID", series),
                                        ("TransferSyntaxUID", ts)) if not valid_uid(val)]
            if missing:
                return self._discard(tmp, StoreOutcome(
                    STATUS_DATASET_MISMATCH, f"Atributos obrigatórios ausentes ou inválidos: {', '.join(missing)}"))
            from app.dicom.uids import is_strict
            lax = [n for n, val in (("SOPInstanceUID", sop), ("StudyInstanceUID", study),
                                    ("SeriesInstanceUID", series)) if not is_strict(val)]
            if lax:     # aceito e guardado sem alteração (equipamentos antigos); só registrado
                log.warning("UID recebido fora da PS3.5 §9.1 (zero à esquerda); aceito sem alteração",
                            extra={"attributes": ",".join(lax), "calling_ae": peer.calling_ae})
            modality = str(ds.get("Modality", "") or "") or None
            try:
                frames = int(ds.get("NumberOfFrames", 1) or 1)
            except (TypeError, ValueError):
                frames = 1
            digest = sha256_file(tmp)
            size = tmp.stat().st_size

            conn = self.db.connection()
            existing = conn.execute("SELECT * FROM instances WHERE sop_instance_uid = ?", (sop,)).fetchone()
            if existing is not None:
                tmp.unlink(missing_ok=True)
                if existing["file_sha256"] == digest:
                    # A instância (já armazenada) é repassada como duplicata: a fila decide pela chave
                    # de idempotência se um reenvio gera ou não uma nova impressão.
                    dup = ReceivedInstance(
                        sop_instance_uid=sop, sop_class_uid=existing["sop_class_uid"], study_uid=existing["study_uid"],
                        series_uid=existing["series_uid"], modality=existing["modality"] or "",
                        transfer_syntax=existing["transfer_syntax"], file_path=Path(existing["file_path"]),
                        file_sha256=digest, peer=peer, device_id=device_id, received_at=utc_now(), duplicate=True)
                    return StoreOutcome(STATUS_SUCCESS, "Duplicata idêntica descartada", duplicate=True, instance=dup)
                log.warning("Conflito de SOP Instance UID: conteúdo diferente; original mantido",
                            extra={"sop_instance_uid": sop})
                return StoreOutcome(STATUS_SUCCESS, "UID já recebido com conteúdo diferente; original mantido",
                                    duplicate=True, conflict=True)

            dest = self.path_for(study, series, sop)
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(tmp, dest)
            received_at = utc_now()
            purge_after = None
            if retention_days:
                from datetime import timedelta
                purge_after = to_iso(received_at + timedelta(days=retention_days))
            try:
                with self.db.transaction():
                    conn.execute(
                        """INSERT INTO instances(sop_instance_uid, sop_class_uid, study_uid, series_uid,
                               modality, transfer_syntax, file_path, file_sha256, file_size,
                               number_of_frames, source_ae, source_ip, device_id, received_at, purge_after)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (sop, sop_class, study, series, modality, ts, str(dest), digest, size, frames,
                         peer.calling_ae, peer.address, device_id, to_iso(received_at), purge_after))
            except Exception:
                dest.unlink(missing_ok=True)
                raise
            instance = ReceivedInstance(
                sop_instance_uid=sop, sop_class_uid=sop_class, study_uid=study, series_uid=series,
                modality=modality or "", transfer_syntax=ts, file_path=dest, file_sha256=digest,
                peer=peer, device_id=device_id, received_at=received_at)
            for listener in self.listeners:
                try:
                    listener(instance, ds, source)
                except Exception:  # noqa: BLE001 - a instância já está gravada
                    log.exception("Falha em ouvinte de instância recebida")
            return StoreOutcome(STATUS_SUCCESS, "Armazenada", instance=instance)
        except OSError as exc:
            log.exception("Falha de disco ao armazenar instância")
            return self._discard(tmp, StoreOutcome(STATUS_OUT_OF_RESOURCES, f"Falha de disco: {exc.strerror or exc}"))
        except Exception as exc:  # noqa: BLE001 - qualquer falha vira status DICOM, nunca derruba o SCP
            log.exception("Falha ao armazenar instância")
            return self._discard(tmp, StoreOutcome(STATUS_PROCESSING_FAILURE, f"Falha de processamento: {type(exc).__name__}"))

    @staticmethod
    def _discard(tmp: Path, outcome: StoreOutcome) -> StoreOutcome:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return outcome

    def count_since(self, since: datetime) -> int:
        return int(self.db.connection().execute(
            "SELECT COUNT(*) FROM instances WHERE received_at >= ?", (to_iso(since),)).fetchone()[0])
