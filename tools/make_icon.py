"""Gera, a partir dos SVG originais da marca:

* ``build/vyonix.ico``             — ícone do executável e do instalador (16–256 px)
* ``build/wizard_large.bmp``       — imagem lateral do assistente do Inno Setup
* ``build/wizard_small.bmp``       — imagem do cabeçalho do assistente

Requer PySide6 (renderização SVG) e Pillow (gravação ICO/BMP).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
ICON_SVG = ROOT / "assets" / "vyonix_icon.svg"
NAVY = QColor("#0A1A33")


def render(svg: Path, size: int) -> QImage:
    renderer = QSvgRenderer(str(svg))
    if not renderer.isValid():
        raise SystemExit(f"SVG inválido: {svg}")
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p, QRectF(0, 0, size, size))
    p.end()
    return img


def to_pil(img: QImage) -> Image.Image:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    from io import BytesIO
    return Image.open(BytesIO(bytes(data))).convert("RGBA")


def wizard_large(width: int = 164, height: int = 314) -> QImage:
    img = QImage(width, height, QImage.Format_RGB32)
    img.fill(NAVY)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(str(ICON_SVG)).render(p, QRectF((width - 96) / 2, 70, 96, 96))
    p.setPen(QColor("#FFFFFF"))
    f = QFont("Segoe UI", 15, QFont.Bold)
    f.setLetterSpacing(QFont.AbsoluteSpacing, 3)
    p.setFont(f)
    p.drawText(QRectF(0, 182, width, 30), Qt.AlignCenter, "VYONIX")
    p.setPen(QColor("#C5CED9"))
    p.setFont(QFont("Segoe UI", 8))
    p.drawText(QRectF(0, 210, width, 20), Qt.AlignCenter, "DICOM PRINT")
    p.setFont(QFont("Segoe UI", 7, -1, True))
    p.drawText(QRectF(0, height - 40, width, 20), Qt.AlignCenter, "Precisão em cada imagem.")
    p.end()
    return img


def main() -> None:
    _app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])  # noqa: F841
    BUILD.mkdir(parents=True, exist_ok=True)
    base = to_pil(render(ICON_SVG, 256))
    sizes = [(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)]
    base.save(BUILD / "vyonix.ico", format="ICO", sizes=sizes)

    to_pil(wizard_large()).convert("RGB").save(BUILD / "wizard_large.bmp", format="BMP")
    small = Image.new("RGB", (58, 58), (255, 255, 255))
    small.paste(to_pil(render(ICON_SVG, 52)), (3, 3), to_pil(render(ICON_SVG, 52)))
    small.save(BUILD / "wizard_small.bmp", format="BMP")

    for name in ("vyonix.ico", "wizard_large.bmp", "wizard_small.bmp"):
        path = BUILD / name
        print(f"{name}: {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
