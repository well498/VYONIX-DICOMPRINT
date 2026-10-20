"""Conversão de imagens numpy (uint8, cinza ou RGB) para QPixmap."""

from __future__ import annotations

from app.ui.qt import QImage, QPixmap, Qt


def to_qimage(arr) -> QImage:
    import numpy as np
    arr = np.ascontiguousarray(arr)
    h, w = arr.shape[:2]
    if arr.ndim == 2:
        img = QImage(arr.data, w, h, w, QImage.Format_Grayscale8)
    elif arr.ndim == 3 and arr.shape[2] == 3:
        img = QImage(arr.data, w, h, 3 * w, QImage.Format_RGB888)
    else:
        raise ValueError(f"Formato de imagem não suportado: {arr.shape}")
    return img.copy()   # a QImage passa a ter seus próprios dados (o array pode ser liberado)


def to_pixmap(arr, max_w: int | None = None, max_h: int | None = None) -> QPixmap:
    pix = QPixmap.fromImage(to_qimage(arr))
    if max_w and max_h and (pix.width() > max_w or pix.height() > max_h):
        pix = pix.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return pix
