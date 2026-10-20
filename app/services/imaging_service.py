"""Fachada de imagens para a interface: instâncias recebidas, pré-visualização e calibração."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from app.core.contracts import PresentationParams, RenderedImage
from app.database.connection import Database
from app.imaging import calibration
from app.imaging.cache import PreviewCache, downscale
from app.imaging.decoder import DecodeError, read_info
from app.imaging.pipeline import PresentationPipeline

PATTERN = "pattern"


class ImagingService:
    def __init__(self, db: Database, cache: PreviewCache) -> None:
        self.db = db
        self.cache = cache
        self.pipeline = PresentationPipeline()

    def recent_instances(self, limit: int = 100) -> list[dict[str, Any]]:
        """Instâncias recebidas, sem dados de paciente."""
        rows = self.db.connection().execute(
            """SELECT i.id, i.received_at, i.modality, i.source_ae, i.number_of_frames, i.transfer_syntax,
                      i.file_sha256, i.file_path, d.name AS device_name
               FROM instances i LEFT JOIN devices d ON d.id = i.device_id
               ORDER BY i.received_at DESC LIMIT ?""", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def instance(self, instance_id: int) -> dict[str, Any]:
        r = self.db.connection().execute("SELECT * FROM instances WHERE id = ?", (instance_id,)).fetchone()
        if r is None:
            raise DecodeError("Imagem não encontrada (pode ter sido removida pela retenção).")
        return dict(r)

    def info(self, path: Path):
        return read_info(path)

    def render(self, source: int | str | Path, params: PresentationParams, *, max_side: int | None = 1400,
               pattern_size: tuple[int, int] = (1600, 1200)) -> RenderedImage:
        """Renderiza uma instância (id), um arquivo (caminho) ou o padrão de teste (``"pattern"``)."""
        if source == PATTERN:
            px = calibration.test_pattern(*pattern_size, dpi=150)
            from app.imaging.pipeline import adjust, geometry, to_uint8
            v, adj = adjust(px.astype("float32") / 255.0, params)
            img, geo = geometry(to_uint8(v), params)
            img = downscale(img, max_side) if max_side else img
            return RenderedImage(pixels=img, photometric="MONOCHROME2", pixel_spacing_mm=(25.4 / 150, 25.4 / 150),
                                 applied={"source": "padrão de teste", **adj, **geo})
        if isinstance(source, int):
            row = self.instance(source)
            path, digest = Path(row["file_path"]), row["file_sha256"]
        else:
            path, digest = Path(source), None
        key = self.cache.key(digest, params, max_side or 0) if digest and max_side else None
        if key:
            cached = self.cache.get(key)
            if cached is not None:
                return RenderedImage(pixels=cached, photometric="RGB" if cached.ndim == 3 else "MONOCHROME2",
                                     pixel_spacing_mm=None, applied={"cache": True})
        rendered = self.pipeline.render(path, params)
        if max_side:
            rendered = replace(rendered, pixels=downscale(rendered.pixels, max_side))
            if key:
                self.cache.put(key, rendered.pixels)
        return rendered

    @staticmethod
    def calibrated(pixels, profile: calibration.CalibrationProfile):
        return calibration.apply(pixels, profile)
