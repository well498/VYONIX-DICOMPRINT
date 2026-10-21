"""Exportação dos exames armazenados (arquivos DICOM originais).

Disponível **sempre** — inclusive com a licença vencida ou a assinatura suspensa: medidas comerciais
nunca bloqueiam o acesso da clínica aos próprios exames. Os arquivos são copiados byte a byte e
conferidos pelo SHA-256 gravado na recepção; o original não é alterado nem removido.

Estrutura: ``<destino>/VYONIX-export-<data>/<Study UID>/<Series UID>/<SOP UID>.dcm`` + ``manifesto.csv``
(identificadores DICOM, tamanho e SHA-256 — sem nome de paciente).
"""

from __future__ import annotations

import csv
import hashlib
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.core.errors import ValidationError
from app.database.repositories.events_repo import Category

_SAFE = set("0123456789.")


def _uid(v: str) -> str:
    v = (v or "").strip()
    return v if v and set(v) <= _SAFE else hashlib.sha1(v.encode()).hexdigest()


@dataclass
class ExportResult:
    folder: Path
    studies: int = 0
    files: int = 0
    bytes: int = 0
    missing: list[str] = field(default_factory=list)
    mismatched: list[str] = field(default_factory=list)


class ExamExporter:
    def __init__(self, db, events) -> None:
        self.db = db
        self.events = events

    def export(self, dest: Path | str, *, actor: str, study_uids: list[str] | None = None,
               exam_ids: list[int] | None = None, date_from: str | None = None, date_to: str | None = None
               ) -> ExportResult:
        dest = Path(dest)
        if not dest.exists():
            raise ValidationError(f"Pasta de destino não encontrada: {dest}")
        conn = self.db.connection()
        q, a = "SELECT i.* FROM instances i WHERE 1=1", []
        if exam_ids:
            q += f" AND i.study_uid IN (SELECT study_uid FROM exams WHERE id IN ({','.join('?' * len(exam_ids))}))"
            a += [int(x) for x in exam_ids]
        if study_uids:
            q += f" AND i.study_uid IN ({','.join('?' * len(study_uids))})"
            a += list(study_uids)
        if date_from:
            q += " AND i.received_at >= ?"
            a.append(date_from)
        if date_to:
            q += " AND i.received_at < ?"
            a.append(date_to + "T23:59:59.999Z" if len(date_to) == 10 else date_to)
        rows = conn.execute(q + " ORDER BY i.study_uid, i.series_uid, i.id", a).fetchall()
        if not rows:
            raise ValidationError("Nenhuma imagem armazenada corresponde à seleção.")
        folder = dest / f"VYONIX-export-{datetime.now():%Y%m%d-%H%M%S}"
        folder.mkdir()
        res = ExportResult(folder)
        studies = set()
        with open(folder / "manifesto.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(["study_uid", "series_uid", "sop_instance_uid", "modality", "arquivo", "bytes", "sha256",
                        "conferido"])
            for r in rows:
                src = Path(r["file_path"])
                rel = Path(_uid(r["study_uid"])) / _uid(r["series_uid"]) / f"{_uid(r['sop_instance_uid'])}.dcm"
                if not src.exists():
                    res.missing.append(r["sop_instance_uid"])
                    w.writerow([r["study_uid"], r["series_uid"], r["sop_instance_uid"], r["modality"], "", 0, "",
                                "ausente (retenção)"])
                    continue
                target = folder / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, target)
                h = hashlib.sha256(target.read_bytes()).hexdigest()
                ok = h == r["file_sha256"]
                if not ok:
                    res.mismatched.append(r["sop_instance_uid"])
                studies.add(r["study_uid"])
                res.files += 1
                res.bytes += target.stat().st_size
                w.writerow([r["study_uid"], r["series_uid"], r["sop_instance_uid"], r["modality"], rel.as_posix(),
                            target.stat().st_size, h, "sim" if ok else "DIVERGENTE"])
        res.studies = len(studies)
        self.events.add(level="WARNING" if res.mismatched else "INFO", category=Category.ADMIN, action="exams.export",
                        message=f"Exportação de {res.studies} exame(s), {res.files} arquivo(s) para {folder}.",
                        actor=actor, details={"files": res.files, "studies": res.studies, "missing": len(res.missing),
                                              "mismatched": len(res.mismatched)})
        return res
