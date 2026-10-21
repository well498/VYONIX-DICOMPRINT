"""Janela principal: cabeçalho da marca, navegação com os 12 itens do menu (§13) e páginas."""

from __future__ import annotations

from app.ui.qt import QSize, Qt
from app.ui.qt import QIcon, QPixmap
from app.ui.qt import (QApplication, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMainWindow, QStackedWidget, QVBoxLayout, QWidget)

from app import __version__, brand
from app.bootstrap import AppContext
from app.ui import theme
from app.ui.pages.base import Page
from app.ui.pages.calibration_page import CalibrationPage
from app.ui.pages.dashboard_page import DashboardPage
from app.ui.pages.devices_page import DevicesPage
from app.ui.pages.jobs_page import JobsPage
from app.ui.pages.printers_page import PrintersPage
from app.ui.pages.profiles_page import ProfilesPage
from app.ui.pages.rules_page import RulesPage
from app.ui.pages.server_page import ServerPage
from app.ui.pages.history_page import HistoryPage
from app.ui.pages.info_pages import AboutPage, LicensePage
from app.ui.pages.settings_page import SettingsPage
from app.ui.workers import wait_all
from app.utils.logging_setup import get_logger
from app.utils.resources import asset_path

log = get_logger("ui.main_window")

MENU = (
    "Dashboard", "Equipamentos DICOM", "Servidor DICOM", "Impressoras", "Trabalhos de impressão",
    "Regras automáticas", "Calibração", "Perfis de impressão", "Histórico", "Configurações",
    "Licença", f"Sobre o {brand.BRAND}",
)


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(f"{brand.PRODUCT_NAME} {__version__}")
        self.setWindowIcon(QIcon(str(asset_path("vyonix_icon.svg"))))
        self.setMinimumSize(QSize(900, 560))

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._header())

        body = QHBoxLayout()
        body.setSpacing(0)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(232)
        self.stack = QStackedWidget()
        body.addWidget(self.nav)
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)
        self.setCentralWidget(central)

        exports = ctx.paths.exports_dir
        self.settings_page = SettingsPage(ctx.settings, exports, ctx.access)
        self.settings_page.settings_saved.connect(self._on_settings_saved)
        pages: list[Page] = [
            DashboardPage(ctx.dashboard),
            DevicesPage(ctx.devices, ctx.access, exports),
            ServerPage(ctx),
            PrintersPage(ctx),
            JobsPage(ctx),
            RulesPage(ctx),
            CalibrationPage(ctx),
            ProfilesPage(ctx),
            HistoryPage(ctx.events, ctx.changes, exports),
            self.settings_page,
            LicensePage(ctx.settings),
            AboutPage(ctx.paths),
        ]
        assert len(pages) == len(MENU)
        for label, page in zip(MENU, pages):
            item = QListWidgetItem(label)
            item.setSizeHint(QSize(220, 38))
            self.nav.addItem(item)
            self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self._navigate)
        self.nav.setCurrentRow(0)

        self.statusBar().showMessage(
            f"Dados: {ctx.paths.machine_root}   ·   {brand.CLINICAL_DISCLAIMER}")

    # ------------------------------------------------------------------
    def _header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("header")
        lay = QHBoxLayout(header)
        lay.setContentsMargins(18, 10, 22, 10)
        icon = QLabel()
        pix = QPixmap(str(asset_path("vyonix_icon.svg")))
        if not pix.isNull():
            icon.setPixmap(pix.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        lay.addWidget(icon)
        names = QVBoxLayout()
        names.setSpacing(0)
        b = QLabel(brand.BRAND)
        b.setObjectName("brand")
        p = QLabel("DICOM PRINT")
        p.setObjectName("product")
        names.addWidget(b)
        names.addWidget(p)
        lay.addLayout(names)
        lay.addStretch(1)
        s = QLabel(brand.SLOGAN)
        s.setObjectName("slogan")
        lay.addWidget(s)
        return header

    def show_fitted(self) -> None:
        """Abre em 1280 x 820 quando cabe; em telas menores (ex.: 1366 x 768) abre maximizada."""
        screen = QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        if avail is None or (avail.width() >= 1320 and avail.height() >= 880):
            self.resize(1280, 820)
            self.show()
            return
        self.setMinimumSize(QSize(min(900, avail.width()), min(560, avail.height())))
        self.resize(min(1280, avail.width()), min(820, avail.height() - 40))
        self.showMaximized()

    def _navigate(self, row: int) -> None:
        if row < 0:
            return
        self.stack.setCurrentIndex(row)
        page = self.stack.currentWidget()
        if isinstance(page, Page):
            page.on_shown()

    def _on_settings_saved(self, changed: dict) -> None:
        if "ui.theme" in changed:
            theme.apply_theme(QApplication.instance(), changed["ui.theme"])

    hide_on_close = False      # definido pela aplicação quando há ícone na bandeja
    quitting = False

    def closeEvent(self, event) -> None:  # noqa: N802 - API Qt
        if self.hide_on_close and not self.quitting:
            event.ignore()
            self.hide()
            return
        super().closeEvent(event)

    def bring_to_front(self) -> None:
        if self.isMinimized() or not self.isVisible():
            self.show_fitted()
        self.raise_()
        self.activateWindow()

    def shutdown(self) -> None:
        """Interrompe atualizações e aguarda operações pendentes antes de fechar o banco."""
        for i in range(self.stack.count()):
            timer = getattr(self.stack.widget(i), "timer", None)
            if timer is not None:
                timer.stop()
        if not wait_all(10000):
            log.warning("Operações pendentes não concluídas no encerramento")
