"""Controle de brilho, contraste ou gama na escala −5,0 … +5,0.

Seta para cima/baixo (±0,5), campo numérico editável (passo fino escolhido: 0,1; 0,2 ou 0,5), barra
deslizante (resolução 0,1), valor atual, botão de restauração e indicador de alteração não salva.
Teclado: no campo, ↑/↓ = passo fino; PgUp/PgDn = ±0,5 (equivalente às setas).
"""

from __future__ import annotations

from app.imaging import tone
from app.ui.qt import (QDoubleSpinBox, QHBoxLayout, QLabel, QSlider, QToolButton, Qt, QWidget, Signal)


class ToneControl(QWidget):
    changed = Signal(float)

    def __init__(self, key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self._saved = 0.0
        self._block = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel(tone.LABELS[key])
        self.title.setMinimumWidth(80)
        self.down = QToolButton()
        self.down.setText("▼")
        self.down.setToolTip(f"Diminuir {tone.LABELS[key].lower()} em 0,5")
        self.down.setAutoRepeat(True)
        self.up = QToolButton()
        self.up.setText("▲")
        self.up.setToolTip(f"Aumentar {tone.LABELS[key].lower()} em 0,5")
        self.up.setAutoRepeat(True)
        self.spin = QDoubleSpinBox()
        self.spin.setRange(tone.MIN, tone.MAX)
        self.spin.setDecimals(1)
        self.spin.setSingleStep(tone.STEP)
        self.spin.setKeyboardTracking(False)
        self.spin.setAccessibleName(tone.LABELS[key])
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(int(tone.MIN * 10), int(tone.MAX * 10))
        self.slider.setSingleStep(1)
        self.slider.setPageStep(5)
        self.slider.setTickInterval(10)
        self.slider.setTickPosition(QSlider.TicksBelow)
        self.slider.setMinimumWidth(180)
        self.value_label = QLabel(tone.fmt(0))
        self.value_label.setMinimumWidth(44)
        self.reset = QToolButton()
        self.reset.setText("↺")
        self.reset.setToolTip("Restaurar o valor salvo")
        self.dirty = QLabel("")
        self.dirty.setObjectName("fieldError")
        self.dirty.setToolTip("Alteração não salva")
        self.dirty.setMinimumWidth(14)
        for w in (self.title, self.down, self.spin, self.up, self.slider, self.value_label, self.reset, self.dirty):
            lay.addWidget(w)
        lay.setStretch(lay.indexOf(self.slider), 1)
        self.up.clicked.connect(lambda _=False: self.set_value(tone.step_value(self.value(), +1)))
        self.down.clicked.connect(lambda _=False: self.set_value(tone.step_value(self.value(), -1)))
        self.spin.valueChanged.connect(lambda v: self.set_value(v))
        self.slider.valueChanged.connect(lambda v: self.set_value(v / 10.0))
        self.reset.clicked.connect(lambda _=False: self.set_value(self._saved))

    def keyPressEvent(self, event) -> None:  # noqa: N802 - API Qt
        if event.key() == Qt.Key_PageUp:
            self.set_value(tone.step_value(self.value(), +1))
        elif event.key() == Qt.Key_PageDown:
            self.set_value(tone.step_value(self.value(), -1))
        else:
            super().keyPressEvent(event)

    def value(self) -> float:
        return tone.snap(self.spin.value())

    def set_fine_step(self, step: float) -> None:
        self.spin.setSingleStep(step)

    def set_value(self, v: float, *, emit: bool = True) -> None:
        if self._block:
            return
        v = tone.snap(v)
        self._block = True
        try:
            self.spin.setValue(v)
            self.slider.setValue(round(v * 10))
            self.value_label.setText(tone.fmt(v))
        finally:
            self._block = False
        self.dirty.setText("●" if abs(v - self._saved) > 1e-9 else "")
        if emit:
            self.changed.emit(v)

    def set_saved(self, v: float) -> None:
        """Define o valor salvo (referência do indicador e do botão de restauração) e o aplica."""
        self._saved = tone.snap(v)
        self.set_value(self._saved, emit=False)

    def is_dirty(self) -> bool:
        return abs(self.value() - self._saved) > 1e-9
