"""Calibração progressiva: rodadas de folhas 3 × 3, escolha da melhor combinação e histórico.

Fluxo: imagem → ajuste inicial → matriz 3 × 3 → impressão → comparação no papel → escolha (1–9) →
os valores escolhidos viram o novo centro → nova matriz com incremento menor → … → salvar no perfil do
equipamento (``DeviceSettingsService.save_tone``, com versão anterior preservada para reverter).

A escolha visual do técnico não é tratada como comprovação de qualidade diagnóstica.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from app.core.errors import ValidationError
from app.database.connection import Database
from app.database.repositories.events_repo import Category, EventRepository
from app.imaging import tone
from app.printing.calibration_sheet import Matrix, build_matrix
from app.utils.timeutil import utc_now_iso

PATTERN = "pattern"


class CalibrationService:
    def __init__(self, db: Database, events: EventRepository, jobs, machine_root: Path) -> None:
        self.db = db
        self.events = events
        self.jobs = jobs
        self.sources_dir = Path(machine_root) / "calibration_sources"

    @staticmethod
    def new_session() -> str:
        return uuid.uuid4().hex

    def stage_source(self, source: Any) -> str:
        """Fonte persistente da folha: 'pattern', 'instance:<id>' ou 'file:<cópia em ProgramData>'.

        Arquivos do computador do usuário são copiados para a pasta de dados, para que o serviço Windows
        (outra conta) consiga lê-los e para que a retenção os remova depois.
        """
        if source == PATTERN or source is None:
            return PATTERN
        if isinstance(source, int):
            return f"instance:{source}"
        path = Path(source)
        if not path.is_file():
            raise ValidationError(f"Arquivo não encontrado: {path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:24]
        target = self.sources_dir / f"{digest}{path.suffix.lower()}"
        if not target.exists():
            self.sources_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        return f"file:{target}"

    @staticmethod
    def resolve_source(stored: str) -> Any:
        if stored == PATTERN:
            return PATTERN
        kind, _, value = stored.partition(":")
        if kind == "instance":
            return int(value)
        if kind == "file":
            return value
        raise ValidationError(f"Fonte de calibração inválida: {stored}")

    def round_count(self, session_id: str) -> int:
        return int(self.db.connection().execute("SELECT COUNT(*) FROM calibration_rounds WHERE session_id = ?",
                                                (session_id,)).fetchone()[0])

    def print_round(self, *, device_id: int | None, session_id: str, center: tone.ToneControls, mode: str,
                    step: float, source: Any, printer: str, paper: str, orientation: str = "landscape",
                    actor: str, device_name: str | None = None, modality: str | None = None) -> tuple[int, int, Matrix]:
        """Cria a folha (trabalho de página de teste) e registra a rodada. Retorna (rodada, trabalho, matriz)."""
        matrix = build_matrix(center, mode, step)
        stored = self.stage_source(source)
        sheet = {"kind": "calibration_matrix", "mode": mode, "step": step, "center": center.to_json(),
                 "source": stored, "device": device_name, "modality": modality, "session": session_id}
        job_id = self.jobs.test_page(printer=printer, actor=actor, device_id=device_id,
                                     overrides={"paper": paper, "orientation": orientation, "sheet": sheet})
        now = utc_now_iso()
        round_no = self.round_count(session_id) + 1
        with self.db.transaction():
            cur = self.db.connection().execute(
                """INSERT INTO calibration_rounds(session_id, device_id, round_no, mode, step, center_json, cells_json,
                       source, printer, paper, job_id, notes, actor, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, device_id, round_no, mode, step, json.dumps(center.to_json()),
                 json.dumps([c.to_json() for c in matrix.cells]), stored, printer, paper, job_id,
                 "; ".join(matrix.notes) or None, actor, now))
            self.events.add(level="INFO", category=Category.PRINTER, action="calibration.round",
                            message=f"Calibração: rodada {round_no} (matriz 3 × 3, {mode}, incremento {step}) "
                                    f"enviada como trabalho #{job_id}.", device_id=device_id, job_id=job_id, actor=actor)
        return int(cur.lastrowid), job_id, matrix

    def choose(self, round_id: int, index: int, *, actor: str) -> tone.ToneControls:
        r = self.db.connection().execute("SELECT * FROM calibration_rounds WHERE id = ?", (round_id,)).fetchone()
        if r is None:
            raise ValidationError("Rodada não encontrada.")
        cells = json.loads(r["cells_json"])
        cell = next((c for c in cells if c["index"] == int(index)), None)
        if cell is None:
            raise ValidationError("Escolha uma imagem de 1 a 9.")
        chosen = tone.ToneControls.from_values(cell)
        with self.db.transaction():
            self.db.connection().execute("UPDATE calibration_rounds SET chosen_index = ?, chosen_at = ? WHERE id = ?",
                                         (int(index), utc_now_iso(), round_id))
            self.events.add(level="INFO", category=Category.PRINTER, action="calibration.choose",
                            message=f"Calibração: na rodada {r['round_no']} foi escolhida a imagem {int(index):02d} "
                                    f"({chosen.label()}).", device_id=r["device_id"], actor=actor)
        return chosen

    def rounds(self, device_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql, params = "SELECT * FROM calibration_rounds", []
        if device_id is not None:
            sql, params = sql + " WHERE device_id = ?", [device_id]
        rows = self.db.connection().execute(sql + " ORDER BY id DESC LIMIT ?", (*params, limit)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["center"] = json.loads(r["center_json"])
            d["cells"] = json.loads(r["cells_json"])
            out.append(d)
        return out
