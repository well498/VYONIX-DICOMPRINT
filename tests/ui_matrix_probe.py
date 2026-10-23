"""Sonda da matriz de resolução, escala (DPI) e monitores (Prompt Mestre §14).

Executada em processo próprio por ``tests/test_ui_matrix.py``, com a plataforma Qt ``offscreen``
configurada por arquivo (telas virtuais com tamanho e DPI lógicos definidos) — a resolução do
computador nunca é alterada. Para cada tema (claro e escuro):

* abre a janela principal como o produto abre (``show_fitted``) e confere se cabe na área útil
  da tela em que foi aberta;
* visita as 13 páginas e procura conteúdo que exija rolagem horizontal, textos cortados (rótulo,
  botão ou caixa de seleção mais estreitos que o próprio texto) e campos sobrepostos;
* abre os diálogos principais e repete as verificações, inclusive se cabem na tela;
* renderiza uma lista suspensa aberta e um menu e mede o contraste real (pixels) entre o texto e
  o fundo.

Uso: ``python -m tests.ui_matrix_probe <saida.json> <pasta_de_dados> <indice_da_tela>``.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

MIN_TEXT_CONTRAST = 4.5


def _lum(c) -> float:
    def ch(v: float) -> float:
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def _ratio(a, b) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def rendered_contrast(widget) -> dict:
    """Fundo = cor mais frequente; texto = pixel de maior contraste com o fundo."""
    from collections import Counter
    img = widget.grab().toImage()
    w, h = img.width(), img.height()
    counts: Counter = Counter()
    step = 1 if w * h < 250_000 else 2
    pixels = []
    for y in range(0, h, step):
        for x in range(0, w, step):
            c = img.pixelColor(x, y)
            rgb = (c.red(), c.green(), c.blue())
            counts[rgb] += 1
            pixels.append(rgb)
    if not counts:
        return {"ratio": 0.0, "background": None, "text": None}
    bg = counts.most_common(1)[0][0]
    best = max(pixels, key=lambda p: _ratio(p, bg))
    return {"ratio": round(_ratio(best, bg), 2), "background": "#%02X%02X%02X" % bg,
            "text": "#%02X%02X%02X" % best, "size": [w, h]}


def layout_issues(root, where: str) -> list[str]:
    """Textos cortados, campos sobrepostos e conteúdo maior que a área rolável."""
    from app.ui.qt import (QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDoubleSpinBox, QLabel,
                           QLineEdit, QPushButton, QRadioButton, QScrollArea, QSpinBox, QWidget)
    issues: list[str] = []
    kinds = (QLabel, QPushButton, QCheckBox, QRadioButton, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
             QDateEdit, QAbstractItemView)

    def visible(wd) -> bool:
        return wd.isVisibleTo(root) and wd.width() > 0 and wd.height() > 0

    def name(wd) -> str:
        text = ""
        for attr in ("text", "currentText", "title"):
            fn = getattr(wd, attr, None)
            if callable(fn):
                try:
                    text = fn() or ""
                except TypeError:
                    text = ""
                if text:
                    break
        text = " ".join(str(text).split())[:40]
        return f"{type(wd).__name__}" + (f" “{text}”" if text else (f" #{wd.objectName()}" if wd.objectName() else ""))

    for scroll in root.findChildren(QScrollArea):
        inner = scroll.widget()
        if inner is None or not visible(scroll):
            continue
        need, have = inner.minimumSizeHint().width(), scroll.viewport().width()
        if need > have + 1:
            issues.append(f"{where}: conteúdo exige {need} px de largura e a área visível tem {have} px "
                          "(rolagem horizontal)")

    widgets = [wd for wd in root.findChildren(QWidget) if isinstance(wd, kinds) and visible(wd)]
    for wd in widgets:
        check = isinstance(wd, (QPushButton, QCheckBox, QRadioButton))
        if isinstance(wd, QLabel) and not wd.wordWrap() and wd.text():
            pm = wd.pixmap()
            check = pm is None or pm.isNull()
        if check:
            hint = wd.sizeHint().width()
            if hint > 0 and wd.width() + 2 < hint:
                issues.append(f"{where}: {name(wd)} cortado ({wd.width()} px de {hint} px)")
        if isinstance(wd, (QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QPushButton)):
            mh = wd.minimumSizeHint().height()
            if mh > 0 and wd.height() + 2 < mh:
                issues.append(f"{where}: {name(wd)} com altura {wd.height()} px abaixo do mínimo {mh} px")

    by_parent: dict[int, list] = {}
    for wd in widgets:
        p = wd.parentWidget()
        if p is not None and p.layout() is not None:
            by_parent.setdefault(id(p), []).append(wd)
    for group in by_parent.values():
        for i, a in enumerate(group):
            ga = a.geometry()
            for b in group[i + 1:]:
                inter = ga.intersected(b.geometry())
                if inter.width() > 2 and inter.height() > 2:
                    issues.append(f"{where}: {name(a)} sobreposto a {name(b)} "
                                  f"({inter.width()}×{inter.height()} px)")
    return issues


def _fits(screen, frame, where: str) -> list[str]:
    avail = screen.availableGeometry()
    if avail.contains(frame):
        return []
    return [f"{where}: janela {frame.width()}×{frame.height()} em ({frame.x()},{frame.y()}) não cabe na área "
            f"útil {avail.width()}×{avail.height()} em ({avail.x()},{avail.y()})"]


def run(out_path: Path, data_dir: Path, screen_index: int) -> dict:
    from app.ui.qt import QApplication, install_translations, prepare_application
    prepare_application()
    app = QApplication(["vyonix-ui-matrix"])
    install_translations(app)
    from app.bootstrap import bootstrap
    from app.printing.backends.pdf import PDF_PRINTER
    from app.ui import theme
    from app.ui.main_window import MENU, MainWindow
    from app.ui.pages.devices_page import DeviceDialog
    from app.ui.pages.device_settings_dialog import DeviceSettingsDialog
    from app.ui.pages.license_page import ActivationDialog
    from app.ui.pages.profiles_page import ProfileDialog
    from app.ui.pages.rules_page import RuleDialog, SimulationDialog
    from app.ui.qt import QComboBox, QMenu
    from app.ui.workers import wait_all

    screens = app.screens()
    screen = screens[min(screen_index, len(screens) - 1)]
    result: dict = {
        "screens": [{"name": s.name(), "geometry": [s.geometry().x(), s.geometry().y(), s.geometry().width(),
                                                     s.geometry().height()],
                     "available": [s.availableGeometry().width(), s.availableGeometry().height()],
                     "dpr": round(s.devicePixelRatio(), 3), "logical_dpi": round(s.logicalDotsPerInch(), 1)}
                    for s in screens],
        "screen_index": screens.index(screen), "issues": [], "pages": 0, "dialogs": 0, "contrast": {},
    }

    def settle():
        for _ in range(3):
            wait_all(5000)
            app.processEvents()

    ctx = bootstrap(data_dir=data_dir)
    try:
        ctx.printers.refresh()
        ctx.settings.update({"printing.default_printer": PDF_PRINTER}, actor="matriz")
        device = ctx.devices.create({"name": "Tomografia Matriz 01", "ae_title": "CT_MTX", "modality": "CT"},
                                    actor="matriz")
        for mode in ("light", "dark"):
            theme.apply_theme(app, mode)
            w = MainWindow(ctx)
            w.show_fitted(screen)
            settle()
            result["issues"] += _fits(screen, w.frameGeometry(), f"[{mode}] janela principal")
            if w.screen() is not screen:
                result["issues"].append(f"[{mode}] janela principal abriu em {w.screen().name()}, "
                                        f"e não em {screen.name()}")
            for row, label in enumerate(MENU):
                w.nav.setCurrentRow(row)
                settle()
                result["issues"] += layout_issues(w, f"[{mode}] {label}")
                result["pages"] += 1

            combo = w.settings_page.findChild(QComboBox)
            if combo is not None:
                combo.showPopup()
                settle()
                view = combo.view()
                c = rendered_contrast(view.viewport())
                result["contrast"][f"{mode}:lista_suspensa"] = c
                if c["ratio"] < MIN_TEXT_CONTRAST:
                    result["issues"].append(f"[{mode}] lista suspensa com contraste {c['ratio']}:1 "
                                            f"(texto {c['text']} sobre {c['background']})")
                combo.hidePopup()
            menu = QMenu(w)
            for t in ("Abrir log", "Pausar sistema", "Retomar sistema"):
                menu.addAction(t)
            menu.popup(w.mapToGlobal(w.rect().center()))
            settle()
            c = rendered_contrast(menu)
            result["contrast"][f"{mode}:menu"] = c
            if c["ratio"] < MIN_TEXT_CONTRAST:
                result["issues"].append(f"[{mode}] menu com contraste {c['ratio']}:1")
            menu.close()

            dialogs = [
                ("Perfil de impressão", lambda: ProfileDialog(w, ctx.profiles, None)),
                ("Regra avançada", lambda: RuleDialog(w, ctx, None)),
                ("Simulação de regras", lambda: SimulationDialog(w, ctx)),
                ("Regra DICOM", lambda: DeviceDialog(w, ctx.devices, ctx=ctx)),
                ("Configuração do equipamento", lambda: DeviceSettingsDialog(w, ctx, device)),
                ("Ativação", lambda: ActivationDialog(ctx)),
            ]
            for title, make in dialogs:
                try:
                    d = make()
                except Exception as exc:  # noqa: BLE001 - registra e segue para os demais
                    result["issues"].append(f"[{mode}] {title}: não abriu ({exc})")
                    continue
                d.show()
                settle()
                result["issues"] += _fits(d.screen() or screen, d.frameGeometry(), f"[{mode}] diálogo {title}")
                result["issues"] += layout_issues(d, f"[{mode}] diálogo {title}")
                if title == "Ativação":
                    c = rendered_contrast(d)
                    result["contrast"][f"{mode}:dialogo"] = c
                    if c["ratio"] < MIN_TEXT_CONTRAST:
                        result["issues"].append(f"[{mode}] diálogo com contraste {c['ratio']}:1")
                d.close()
                d.deleteLater()
                result["dialogs"] += 1
            w.shutdown()
            w.close()
            w.deleteLater()
            settle()
    finally:
        wait_all(5000)
        ctx.close()
    # sem duplicatas, na ordem em que apareceram
    result["issues"] = list(dict.fromkeys(result["issues"]))
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


def main(argv: list[str]) -> int:
    out, data, idx = Path(argv[0]), Path(argv[1]), int(argv[2])
    try:
        run(out, data, idx)
        return 0
    except Exception:  # noqa: BLE001
        out.write_text(json.dumps({"crash": traceback.format_exc()}, ensure_ascii=False), encoding="utf-8")
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
