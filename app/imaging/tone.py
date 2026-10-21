"""Controles tonais do equipamento: brilho, contraste e gama na escala visual de −5,0 a +5,0.

O valor 0,0 é neutro nos três controles. Cada controle tem uma transformação **própria**,
aplicada sobre a imagem normalizada [0, 1] em ponto flutuante (float32) **dentro** do pipeline de
apresentação, antes da conversão para 8 bits — sem quantização prematura. Ordem de aplicação:

1. inversão (opcional): ``v = 1 − v``;
2. **contraste** — ganho em torno do cinza médio 0,5: ``v = (v − 0,5) · k + 0,5`` com
   ``k = 2^(contraste / 5)`` → controle −5 = ganho 0,5; 0 = 1,0; +5 = 2,0;
3. **brilho** — deslocamento tonal: ``v = v + 0,05 · brilho`` → controle ±5 = ±0,25 (±25 % da faixa);
   em seguida o resultado é limitado a [0, 1];
4. **gama** — ``γ = 2^(gama / 5)`` (−5 → 0,5; 0 → 1,0; +5 → 2,0) aplicado como
   **``v = v^(1/γ)``**: gama positivo **clareia** os tons médios; negativo escurece. Preto (0) e
   branco (1) não mudam.

Essas fórmulas são parâmetros iniciais de engenharia (documentados para evoluir com os testes de
qualidade de impressão). A avaliação visual não comprova qualidade diagnóstica.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from typing import Any

from app.core.contracts import PresentationParams
from app.core.errors import ValidationError

MIN, MAX = -5.0, 5.0
STEP = 0.5
FINE_STEPS = (0.1, 0.2, 0.5)
BRIGHTNESS_PER_UNIT = 0.05


def brightness_offset(control: float) -> float:
    return BRIGHTNESS_PER_UNIT * float(control)


def contrast_gain(control: float) -> float:
    return 2.0 ** (float(control) / 5.0)


def gamma_real(control: float) -> float:
    return 2.0 ** (float(control) / 5.0)


def snap(value: float, step: float = 0.1) -> float:
    """Arredonda para a grade do controle (0,1) e limita a −5..+5."""
    v = round(round(float(value) / step) * step, 1)
    return max(MIN, min(MAX, v)) + 0.0


def step_value(value: float, direction: int, step: float = STEP) -> float:
    """Seta para cima (+1) ou para baixo (−1)."""
    return snap(float(value) + direction * step)


def fmt(value: float) -> str:
    """'+0,5', '0,0', '−1,5' (vírgula decimal e sinal de menos tipográfico)."""
    v = round(float(value), 1) + 0.0
    text = f"{abs(v):.1f}".replace(".", ",")
    return ("+" if v > 0 else "−" if v < 0 else "") + text


@dataclass(frozen=True)
class ToneControls:
    brightness: float = 0.0
    contrast: float = 0.0
    gamma: float = 0.0
    invert: bool = False

    def validate(self) -> "ToneControls":
        for name in ("brightness", "contrast", "gamma"):
            v = getattr(self, name)
            if not isinstance(v, (int, float)) or math.isnan(float(v)) or not MIN <= float(v) <= MAX:
                raise ValidationError(f"{LABELS[name]} deve estar entre −5,0 e +5,0.")
            if abs(round(float(v), 1) - float(v)) > 1e-6:
                raise ValidationError(f"{LABELS[name]}: use passos de 0,1.")
        return self

    def is_neutral(self) -> bool:
        return self == ToneControls()

    def with_(self, **kw) -> "ToneControls":
        return replace(self, **{k: (snap(v) if k != "invert" else bool(v)) for k, v in kw.items()})

    def to_params(self, base: PresentationParams | None = None) -> PresentationParams:
        """Converte para os parâmetros do pipeline (unidades matemáticas)."""
        base = base or PresentationParams()
        return replace(base, invert=bool(self.invert) != bool(base.invert),
                       brightness=brightness_offset(self.brightness), contrast=contrast_gain(self.contrast),
                       gamma=gamma_real(self.gamma))

    def label(self) -> str:
        return f"B {fmt(self.brightness)} | C {fmt(self.contrast)} | G {fmt(self.gamma)}" + (" | INV" if self.invert
                                                                                             else "")

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_values(cls, values: dict[str, Any] | None) -> "ToneControls":
        v = values or {}
        return cls(brightness=float(v.get("brightness") or 0.0), contrast=float(v.get("contrast") or 0.0),
                   gamma=float(v.get("gamma") or 0.0), invert=bool(v.get("invert") or False)).validate()


LABELS = {"brightness": "Brilho", "contrast": "Contraste", "gamma": "Gama"}


def apply_float(v, tone: ToneControls):
    """Mesma transformação do pipeline, para arrays float32 [0, 1] (usada nos testes e na documentação)."""
    import numpy as np
    v = np.asarray(v, dtype=np.float32)
    if tone.invert:
        v = 1.0 - v
    v = (v - 0.5) * np.float32(contrast_gain(tone.contrast)) + 0.5
    v = v + np.float32(brightness_offset(tone.brightness))
    v = np.clip(v, 0.0, 1.0)
    g = gamma_real(tone.gamma)
    if g != 1.0:
        v = np.power(v, np.float32(1.0 / g))
    return v
