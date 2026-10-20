"""Temas claro e escuro gerados a partir da paleta oficial (``app.brand.COLORS``)."""

from __future__ import annotations

from app.ui.qt import Qt
from app.ui.qt import QApplication

from app.brand import COLORS

LIGHT = {
    "bg": "#F4F6F9", "surface": "#FFFFFF", "surface_alt": COLORS["silver_light"],
    "text": "#14202E", "muted": "#5B6B7F", "border": "#D7DEE7",
    "nav_bg": COLORS["navy"], "nav_text": "#C9D4E3", "nav_active": COLORS["blue"],
    "accent": COLORS["blue"], "accent_hover": COLORS["blue_dark"],
    "ok": COLORS["green"], "warn": COLORS["amber"], "err": COLORS["red"],
    "input_bg": "#FFFFFF",
}
DARK = {
    "bg": "#0E1520", "surface": "#162131", "surface_alt": "#1C2A3D",
    "text": "#E7EDF5", "muted": "#93A3B8", "border": "#2A3A50",
    "nav_bg": "#08111D", "nav_text": "#AEBBCD", "nav_active": COLORS["blue"],
    "accent": "#3B82FF", "accent_hover": COLORS["blue"],
    "ok": "#2DBE3A", "warn": "#E0A030", "err": "#F0614F",
    "input_bg": "#101A28",
}

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


def apply_theme(app: QApplication, setting: str) -> str:
    global _current
    mode = resolve_mode(app, setting)
    _current = DARK if mode == "dark" else LIGHT
    app.setStyle("Fusion")
    app.setStyleSheet(stylesheet(_current))
    return mode


def stylesheet(p: dict[str, str]) -> str:
    return f"""
    QWidget {{ color: {p['text']}; font-family: "Segoe UI", "Inter", Arial, sans-serif; font-size: 10pt; }}
    QMainWindow, QWidget#page, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {p['bg']}; }}
    QWidget#header {{ background: {p['surface']}; border-bottom: 1px solid {p['border']}; }}
    QLabel#brand {{ color: {p['accent']}; font-size: 17pt; font-weight: 700; letter-spacing: 4px; }}
    QLabel#product {{ color: {p['muted']}; font-size: 9pt; letter-spacing: 2px; }}
    QLabel#slogan {{ color: {p['muted']}; font-style: italic; }}
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
    QLineEdit, QSpinBox, QComboBox, QDateEdit {{ background: {p['input_bg']}; border: 1px solid {p['border']}; border-radius: 5px; padding: 5px 7px; min-height: 20px; }}
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QDateEdit:focus {{ border: 1px solid {p['accent']}; }}
    QLineEdit[invalid="true"], QSpinBox[invalid="true"] {{ border: 1px solid {p['err']}; }}
    QLineEdit:read-only {{ background: {p['surface_alt']}; }}
    QPushButton {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 5px; padding: 6px 14px; }}
    QPushButton:hover {{ border-color: {p['accent']}; }}
    QPushButton:disabled {{ color: {p['muted']}; }}
    QPushButton#primary {{ background: {p['accent']}; color: #FFFFFF; border: 1px solid {p['accent']}; font-weight: 600; }}
    QPushButton#primary:hover {{ background: {p['accent_hover']}; }}
    QTableWidget {{ background: {p['surface']}; alternate-background-color: {p['surface_alt']}; gridline-color: {p['border']}; border: 1px solid {p['border']}; border-radius: 6px; }}
    QHeaderView::section {{ background: {p['surface_alt']}; border: none; border-bottom: 1px solid {p['border']}; padding: 6px; font-weight: 600; }}
    QTabWidget::pane {{ border: none; }}
    QTabBar::tab {{ padding: 7px 16px; border-bottom: 2px solid transparent; }}
    QTabBar::tab:selected {{ border-bottom: 2px solid {p['accent']}; color: {p['accent']}; }}
    QStatusBar {{ background: {p['surface']}; border-top: 1px solid {p['border']}; color: {p['muted']}; }}
    """
