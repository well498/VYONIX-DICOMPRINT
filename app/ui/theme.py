"""Temas claro e escuro gerados a partir da paleta oficial (``app.brand.COLORS``).

Correção de legibilidade (Prompt Mestre §14): antes, só a folha de estilo mudava com o tema e a
paleta do Qt continuava clara. No tema escuro, o texto claro herdado por ``QWidget`` aparecia sobre
o fundo claro da paleta em listas suspensas (``QComboBox``/``QAbstractItemView``), menus
(``QMenu``), caixas de mensagem (``QMessageBox``) e diálogos — ilegível. Agora:

* a ``QPalette`` do aplicativo é montada com os mesmos tokens do tema (grupos ativo, inativo e
  desabilitado), então qualquer widget sem regra específica já fica coerente;
* a folha de estilo cobre explicitamente listas suspensas, menus, barras de rolagem, dicas e
  diálogos.

Os tokens e os contrastes mínimos (WCAG 2.2 AA) ficam em ``app.ui.tokens`` e são verificados
por testes sem Qt; ``tests/test_ui_matrix.py`` confere o resultado renderizado com o Qt real.
"""

from __future__ import annotations

from app.ui.qt import QApplication, QColor, Qt, QtGui
from app.ui.tokens import DARK, LIGHT, THEMES  # noqa: F401 - reexportados

_current: dict[str, str] = LIGHT


def palette() -> dict[str, str]:
    return _current


def resolve_mode(app: QApplication, setting: str) -> str:
    if setting in ("light", "dark"):
        return setting
    try:  # Qt >= 6.5
        if app.styleHints().colorScheme() == Qt.ColorScheme.Dark:
            return "dark"
    except AttributeError:
        pass
    return "light"


def build_palette(p: dict[str, str]):
    """``QPalette`` equivalente aos tokens (inclusive o grupo desabilitado)."""
    pal = QtGui.QPalette()
    R, G = QtGui.QPalette.ColorRole, QtGui.QPalette.ColorGroup
    roles = {
        R.Window: p["bg"], R.WindowText: p["text"],
        R.Base: p["input_bg"], R.AlternateBase: p["surface_alt"],
        R.Text: p["text"], R.Button: p["surface"], R.ButtonText: p["text"],
        R.BrightText: p["err"], R.Highlight: p["accent_fill"],
        R.HighlightedText: p["on_accent"], R.ToolTipBase: p["tooltip_bg"],
        R.ToolTipText: p["tooltip_text"], R.Link: p["accent"], R.LinkVisited: p["accent"],
        R.Light: p["surface"], R.Midlight: p["surface_alt"], R.Mid: p["border"],
        R.Dark: p["border_strong"], R.Shadow: "#000000",
    }
    placeholder = getattr(R, "PlaceholderText", None)
    if placeholder is not None:
        roles[placeholder] = p["muted"]
    for role, color in roles.items():
        for group in (G.Active, G.Inactive):
            pal.setColor(group, role, QColor(color))
        pal.setColor(G.Disabled, role, QColor(color))
    for role in (R.WindowText, R.Text, R.ButtonText):
        pal.setColor(G.Disabled, role, QColor(p["disabled_text"]))
    pal.setColor(G.Disabled, R.Highlight, QColor(p["border_strong"]))
    return pal


def apply_theme(app: QApplication, setting: str) -> str:
    global _current
    mode = resolve_mode(app, setting)
    _current = THEMES[mode]
    app.setStyle("Fusion")
    from app.ui import responsive
    responsive.install(app)
    app.setPalette(build_palette(_current))
    app.setStyleSheet(stylesheet(_current))
    return mode


def stylesheet(p: dict[str, str]) -> str:
    return f"""
    QWidget {{ color: {p['text']}; font-family: "Segoe UI", "Inter", Arial, sans-serif; font-size: 10pt; }}
    QMainWindow, QDialog, QMessageBox, QInputDialog, QWidget#page, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {p['bg']}; }}
    QWidget:disabled {{ color: {p['disabled_text']}; }}
    QWidget#header {{ background: {p['surface']}; border-bottom: 1px solid {p['border']}; }}
    QLabel#brand {{ color: {p['accent']}; font-size: 17pt; font-weight: 700; letter-spacing: 4px; }}
    QLabel#product {{ color: {p['muted']}; font-size: 9pt; letter-spacing: 2px; }}
    QLabel#slogan {{ color: {p['muted']}; font-style: italic; }}
    QLabel#pauseBadge {{ background: {p['warn']}; color: {p['bg']}; border-radius: 4px; padding: 3px 10px; font-weight: 700; }}
    QListWidget#nav {{ background: {p['nav_bg']}; color: {p['nav_text']}; border: none; outline: 0; padding-top: 8px; }}
    QListWidget#nav::item {{ padding: 9px 18px; border-left: 3px solid transparent; }}
    QListWidget#nav::item:hover {{ background: rgba(255,255,255,0.06); color: #FFFFFF; }}
    QListWidget#nav::item:selected {{ background: rgba(20,96,242,0.22); color: #FFFFFF; border-left: 3px solid {p['nav_active']}; }}
    QLabel#pageTitle {{ font-size: 16pt; font-weight: 600; }}
    QLabel#pageSubtitle, QLabel#muted {{ color: {p['muted']}; }}
    QFrame#card, QGroupBox {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 8px; }}
    QGroupBox {{ margin-top: 14px; padding: 14px 12px 10px 12px; font-weight: 600; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {p['accent']}; }}
    QLabel#cardTitle {{ color: {p['muted']}; font-size: 9pt; font-weight: 600; text-transform: uppercase; }}
    QLabel#cardValue {{ font-size: 20pt; font-weight: 600; }}
    QLabel#ok {{ color: {p['ok']}; font-weight: 600; }}
    QLabel#warn {{ color: {p['warn']}; font-weight: 600; }}
    QLabel#err {{ color: {p['err']}; font-weight: 600; }}
    QLabel#fieldError {{ color: {p['err']}; font-size: 9pt; }}
    QLabel#banner {{ background: {p['surface_alt']}; border: 1px solid {p['border']}; border-radius: 6px; padding: 10px; }}
    QLabel#banner[state="ok"] {{ border-left: 4px solid {p['ok']}; }}
    QLabel#banner[state="warn"] {{ border-left: 4px solid {p['warn']}; }}
    QLabel#banner[state="err"] {{ border-left: 4px solid {p['err']}; }}
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateEdit, QPlainTextEdit {{ background: {p['input_bg']}; color: {p['text']}; border: 1px solid {p['border_strong']}; border-radius: 5px; padding: 5px 7px; }}
    QLineEdit, QComboBox {{ min-height: 20px; }}
    QSpinBox, QDoubleSpinBox, QDateEdit {{ padding: 4px 6px; }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QDateEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {p['accent']}; }}
    QLineEdit[invalid="true"], QSpinBox[invalid="true"], QDoubleSpinBox[invalid="true"] {{ border: 1px solid {p['err']}; }}
    QLineEdit:read-only {{ background: {p['surface_alt']}; }}
    QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled, QDateEdit:disabled {{ background: {p['surface_alt']}; color: {p['disabled_text']}; }}
    QComboBox QAbstractItemView, QComboBox QListView {{ background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border_strong']}; outline: 0; selection-background-color: {p['accent_fill']}; selection-color: {p['on_accent']}; }}
    QComboBox QAbstractItemView::item {{ min-height: 24px; padding: 2px 8px; }}
    QComboBox QAbstractItemView::item:selected, QComboBox QAbstractItemView::item:hover {{ background: {p['accent_fill']}; color: {p['on_accent']}; }}
    QAbstractItemView {{ background: {p['surface']}; color: {p['text']}; selection-background-color: {p['accent_fill']}; selection-color: {p['on_accent']}; }}
    QMenu {{ background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border_strong']}; padding: 4px; }}
    QMenu::item {{ padding: 6px 22px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {p['accent_fill']}; color: {p['on_accent']}; }}
    QMenu::item:disabled {{ color: {p['disabled_text']}; }}
    QMenu::separator {{ height: 1px; background: {p['border']}; margin: 4px 6px; }}
    QToolTip {{ background: {p['tooltip_bg']}; color: {p['tooltip_text']}; border: 1px solid {p['border_strong']}; padding: 4px 6px; }}
    QScrollBar:vertical {{ background: {p['surface_alt']}; width: 12px; margin: 0; }}
    QScrollBar:horizontal {{ background: {p['surface_alt']}; height: 12px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {p['scroll_handle']}; min-height: 28px; border-radius: 5px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {p['scroll_handle']}; min-width: 28px; border-radius: 5px; margin: 2px; }}
    QScrollBar::handle:hover {{ background: {p['scroll_handle_hover']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
    QPushButton {{ background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border_strong']}; border-radius: 5px; padding: 6px 14px; }}
    QPushButton:hover {{ border-color: {p['accent']}; }}
    QPushButton:disabled {{ color: {p['disabled_text']}; border-color: {p['border']}; }}
    QPushButton#primary {{ background: {p['accent_fill']}; color: {p['on_accent']}; border: 1px solid {p['accent_fill']}; font-weight: 600; }}
    QPushButton#primary:hover {{ background: {p['accent_fill_hover']}; }}
    QPushButton#primary:disabled {{ background: {p['border']}; color: {p['disabled_text']}; }}
    QCheckBox, QRadioButton {{ background: transparent; }}
    QTableWidget {{ background: {p['surface']}; alternate-background-color: {p['surface_alt']}; gridline-color: {p['border']}; border: 1px solid {p['border']}; border-radius: 6px; }}
    QHeaderView::section {{ background: {p['surface_alt']}; color: {p['text']}; border: none; border-bottom: 1px solid {p['border']}; padding: 6px; font-weight: 600; }}
    QTabWidget::pane {{ border: none; }}
    QTabBar::tab {{ padding: 7px 16px; border-bottom: 2px solid transparent; }}
    QTabBar::tab:selected {{ border-bottom: 2px solid {p['accent']}; color: {p['accent']}; }}
    QStatusBar {{ background: {p['surface']}; border-top: 1px solid {p['border']}; color: {p['muted']}; }}
    """
