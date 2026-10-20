"""Cache em disco de pré-visualizações (§6 itens 23–24).

Chave = SHA-256 do arquivo original + quadro + parâmetros de apresentação + tamanho máximo.
As imagens ficam em ``cache/previews`` como PNG reduzido; o cache é limitado por tamanho
(padrão 256 MB) e os itens mais antigos são removidos primeiro.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path

from app.core.contracts import PresentationParams
from app.utils.logging_setup import get_logger

log = get_logger("imaging.cache")


class PreviewCache:
    def __init__(self, folder: Path, max_bytes: int = 256 * 1048576) -> None:
        self.folder = folder
        self.max_bytes = max_bytes

    def key(self, file_sha256: str, params: PresentationParams, max_side: int) -> str:
        raw = json.dumps({"f": file_sha256, "p": asdict(params), "s": max_side}, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, key: str):
        import numpy as np
        from PIL import Image
        path = self.folder / f"{key}.png"
        if not path.exists():
            return None
        try:
            with Image.open(path) as im:
                arr = np.asarray(im.convert(im.mode))
            os.utime(path)   # marca uso recente
            return arr
        except OSError:
            path.unlink(missing_ok=True)
            return None

    def put(self, key: str, pixels) -> None:
        from PIL import Image
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self.folder / f"{key}.tmp"
        Image.fromarray(pixels).save(tmp, format="PNG", optimize=False)
        os.replace(tmp, self.folder / f"{key}.png")
        self.prune()

    def prune(self) -> int:
        files = sorted(self.folder.glob("*.png"), key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in files)
        removed = 0
        while files and total > self.max_bytes:
            victim = files.pop(0)
            total -= victim.stat().st_size
            victim.unlink(missing_ok=True)
            removed += 1
        return removed


def downscale(pixels, max_side: int):
    """Reduz preservando a proporção (Lanczos)."""
    import numpy as np
    from PIL import Image
    h, w = pixels.shape[:2]
    scale = max_side / max(h, w)
    if scale >= 1:
        return pixels
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    return np.asarray(Image.fromarray(pixels).resize(size, Image.Resampling.LANCZOS))
