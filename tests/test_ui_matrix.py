"""Matriz de resolução, escala e monitores da interface (Prompt Mestre §14) com o Qt real.

Cada configuração roda ``tests/ui_matrix_probe.py`` num processo próprio, com a plataforma
``offscreen`` lendo um arquivo de telas virtuais (tamanho em pixels físicos e DPI lógico, como o
Windows informa ao Qt em 100 %, 125 %, 150 % e 200 %). A resolução do computador não é tocada.

O resultado de cada configuração (telas efetivas, páginas e diálogos verificados, contrastes
medidos) é gravado em ``dist/validation/ui_matrix/`` quando ``VYONIX_UI_MATRIX_OUT`` aponta para a
pasta — é a evidência usada pelo CI.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from app.ui import qt as _qt  # noqa: F401
    HAS_QT = True
except ImportError:
    HAS_QT = False

ROOT = Path(__file__).resolve().parents[1]

# (nome, telas [(largura, altura, escala)], índice da tela em que a janela abre)
CONFIGS: list[tuple[str, list[tuple[int, int, float]], int]] = [
    ("1366x768_100", [(1366, 768, 1.0)], 0),
    ("1366x768_125", [(1366, 768, 1.25)], 0),
    ("1600x900_100", [(1600, 900, 1.0)], 0),
    ("1920x1080_100", [(1920, 1080, 1.0)], 0),
    ("1920x1080_125", [(1920, 1080, 1.25)], 0),
    ("1920x1080_150", [(1920, 1080, 1.5)], 0),
    ("2560x1440_100", [(2560, 1440, 1.0)], 0),
    ("2560x1440_150", [(2560, 1440, 1.5)], 0),
    ("3840x2160_150", [(3840, 2160, 1.5)], 0),
    ("3840x2160_200", [(3840, 2160, 2.0)], 0),
    ("2_monitores_1920_100+2560_150", [(1920, 1080, 1.0), (2560, 1440, 1.5)], 1),
]


def screens_config(screens: list[tuple[int, int, float]]) -> dict:
    out, x = [], 0
    for i, (w, h, scale) in enumerate(screens):
        out.append({"name": f"tela{i + 1}", "x": x, "y": 0, "width": w, "height": h,
                    "logicalDpi": round(96 * scale), "logicalBaseDpi": 96, "dpr": 1})
        x += w
    return {"synchronousWindowSystemEvents": True, "windowFrameMargins": False, "screens": out}


def run_config(name: str, screens, index: int) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix=f"vyx-ui-{name}-"))
    cfg = tmp / "telas.json"
    cfg.write_text(json.dumps(screens_config(screens)), encoding="utf-8")
    out = tmp / "resultado.json"
    env = dict(os.environ)
    # o Qt separa os parâmetros da plataforma por ":" — um caminho com letra de unidade (C:\\...) quebraria;
    # por isso o processo roda na pasta do arquivo e o caminho é relativo.
    env["QT_QPA_PLATFORM"] = f"offscreen:configfile={cfg.name}"
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(ROOT), env.get("PYTHONPATH", "")) if p)
    for k in ("QT_SCALE_FACTOR", "QT_SCREEN_SCALE_FACTORS", "QT_AUTO_SCREEN_SCALE_FACTOR", "QT_ENABLE_HIGHDPI_SCALING"):
        env.pop(k, None)
    env["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"
    proc = subprocess.run([sys.executable, "-m", "tests.ui_matrix_probe", str(out), str(tmp / "dados"), str(index)],
                          cwd=tmp, env=env, capture_output=True, text=True, timeout=600)
    data = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {
        "crash": f"código {proc.returncode}\n{proc.stdout[-2000:]}\n{proc.stderr[-4000:]}"}
    data["config"] = {"name": name, "screens": screens, "open_on": index}
    dest = os.environ.get("VYONIX_UI_MATRIX_OUT")
    if dest:
        Path(dest).mkdir(parents=True, exist_ok=True)
        (Path(dest) / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


@unittest.skipUnless(HAS_QT, "PySide6 não instalado")
class UiMatrixTest(unittest.TestCase):
    def check(self, name, screens, index):
        data = run_config(name, screens, index)
        self.assertNotIn("crash", data, data.get("crash"))
        # a configuração foi aplicada de fato (escala e tamanho lógico efetivos)
        eff = data["screens"]
        self.assertEqual(len(eff), len(screens))
        for (w, h, scale), s in zip(screens, eff):
            self.assertAlmostEqual(s["dpr"], scale, places=2, msg=f"escala efetiva {s}")
            self.assertLessEqual(abs(s["geometry"][2] - w / scale), 1, s)
            self.assertLessEqual(abs(s["geometry"][3] - h / scale), 1, s)
        self.assertEqual(data["screen_index"], index)
        self.assertEqual(data["pages"], 26)          # 13 páginas × 2 temas
        self.assertEqual(data["dialogs"], 12)        # 6 diálogos × 2 temas
        self.assertEqual(len(data["contrast"]), 6)
        self.assertEqual(data["issues"], [], "\n".join(data["issues"][:40]))


def _make(name, screens, index):
    def test(self):
        self.check(name, screens, index)
    test.__doc__ = f"Interface em {name}"
    return test


for _name, _screens, _index in CONFIGS:
    setattr(UiMatrixTest, f"test_{_name.replace('+', '_')}", _make(_name, _screens, _index))


if __name__ == "__main__":
    unittest.main()
