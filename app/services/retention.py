"""Política de retenção (§16, LGPD): remove imagens e eventos mais antigos que o configurado.

* Imagens: removidas após ``retention.images_days``. Uma imagem ainda ligada a um trabalho em
  andamento (não concluído/cancelado/enviado) é mantida até o trabalho terminar; nos trabalhos
  encerrados a referência é desfeita e o trabalho continua no histórico, sem a imagem.
* Exclusão: o conteúdo do arquivo é sobrescrito com zeros antes da remoção (melhor esforço — em
  SSD e em sistemas com cópias de sombra isso não garante a irrecuperabilidade; para isso use
  criptografia de disco, ex.: BitLocker).
* Eventos: removidos após ``retention.events_days``.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable

from app.database.connection import Database
from app.database.repositories.events_repo import Category, EventRepository
from app.utils.logging_setup import get_logger
from app.utils.timeutil import to_iso, utc_now

log = get_logger("retention")

FINISHED_JOB_STATES = ("completed", "cancelled", "spooled")


def overwrite_and_delete(path: Path) -> bool:
    try:
        size = path.stat().st_size
        with path.open("r+b") as fh:
            remaining = size
            block = b"\0" * (1 << 20)
            while remaining > 0:
                n = min(remaining, len(block))
                fh.write(block[:n])
                remaining -= n
            fh.flush()
            os.fsync(fh.fileno())
        path.unlink()
        return True
    except FileNotFoundError:
        return True
    except OSError:
        log.warning("Não foi possível remover arquivo na retenção", extra={"file": path.name})
        return False


class RetentionService:
    def __init__(self, db: Database, events: EventRepository, settings_get: Callable[[str], Any],
                 storage_dir: Path, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir
        self.db = db
        self.events = events
        self.get = settings_get
        self.storage_dir = storage_dir

    def purge(self, *, now=None, actor: str = "system") -> dict[str, int]:
        now = now or utc_now()
        cutoff = to_iso(now - timedelta(days=int(self.get("retention.images_days"))))
        conn = self.db.connection()
        marks = ",".join("?" * len(FINISHED_JOB_STATES))
        with self.db.transaction():
            conn.execute(
                f"""UPDATE job_items SET instance_id = NULL
                    WHERE instance_id IN (SELECT id FROM instances WHERE received_at < ?)
                      AND job_id IN (SELECT id FROM jobs WHERE state IN ({marks}))""",
                (cutoff, *FINISHED_JOB_STATES))
            rows = conn.execute(
                """SELECT id, file_path, file_size FROM instances
                   WHERE received_at < ?
                     AND id NOT IN (SELECT instance_id FROM job_items WHERE instance_id IS NOT NULL)""",
                (cutoff,)).fetchall()
        removed = freed = 0
        for row in rows:
            path = Path(row["file_path"])
            if overwrite_and_delete(path):
                with self.db.transaction():
                    conn.execute("DELETE FROM instances WHERE id = ?", (row["id"],))
                removed += 1
                freed += int(row["file_size"] or 0)
                _prune_empty_dirs(path.parent, self.storage_dir)
        outputs = 0
        if self.output_dir is not None and self.output_dir.exists():
            limit = (now - timedelta(days=int(self.get("retention.images_days")))).timestamp()
            for f in self.output_dir.rglob("*.pdf"):
                try:
                    if f.stat().st_mtime < limit and overwrite_and_delete(f):
                        outputs += 1
                except OSError:
                    continue
        if self.output_dir is not None:      # imagens copiadas para calibração (mesmo prazo das imagens)
            cal_dir = self.output_dir.parent / "calibration_sources"
            if cal_dir.exists():
                limit = (now - timedelta(days=int(self.get("retention.images_days")))).timestamp()
                for f in cal_dir.iterdir():
                    try:
                        if f.is_file() and f.stat().st_mtime < limit and overwrite_and_delete(f):
                            outputs += 1
                    except OSError:
                        continue
        events_removed = self.events.purge_older_than(int(self.get("retention.events_days")))
        if removed or events_removed or outputs:
            self.events.add(level="INFO", category=Category.SYSTEM, action="retention.purge",
                            message=f"Retenção: {removed} imagem(ns) removida(s) "
                                    f"({freed / 1048576:.1f} MB), {outputs} PDF(s) gerado(s) e "
                                    f"{events_removed} evento(s) antigos.",
                            actor=actor)
        return {"instances": removed, "bytes": freed, "events": events_removed, "outputs": outputs}


def _prune_empty_dirs(folder: Path, root: Path) -> None:
    try:
        root = root.resolve()
        folder = folder.resolve()
        while folder != root and root in folder.parents:
            if any(folder.iterdir()):
                return
            folder.rmdir()
            folder = folder.parent
    except OSError:
        return
