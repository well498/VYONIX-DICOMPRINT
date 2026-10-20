"""Páginas informativas: Licença e Sobre."""

from __future__ import annotations

from app.ui.qt import QT_API, QT_VERSION, Qt
from app.ui.qt import QPixmap
from app.ui.qt import QApplication, QHBoxLayout, QLabel, QPushButton, QWidget

from app import __phase__, __version__, brand
from app.services.settings_service import SettingsService
from app.ui.pages.base import Page, banner, card
from app.ui.workers import run_async
from app.utils.paths import AppPaths
from app.utils.resources import asset_path


class LicensePage(Page):
    def __init__(self, settings: SettingsService, parent: QWidget | None = None) -> None:
        super().__init__("Licença", parent=parent)
        self.settings = settings
        self.body.addWidget(banner(
            "<b>Licença não ativada.</b> O licenciamento offline com assinatura digital "
            "(Ed25519), código de solicitação e ativação por arquivo será entregue na "
            "<b>Fase 8</b>. Nesta versão de desenvolvimento nenhum recurso é bloqueado."))
        frame, lay = card("Identificação da instalação")
        row = QHBoxLayout()
        self.installation = QLabel("—")
        self.installation.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(self.installation, 1)
        copy = QPushButton("Copiar")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.installation.text()))
        row.addWidget(copy)
        lay.addLayout(row)
        hint = QLabel("Este identificador será usado para gerar o código de solicitação de licença.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.body.addWidget(frame)
        self.body.addStretch(1)

    def on_shown(self) -> None:
        run_async(lambda: self.settings.get("system.installation_id"), self.installation.setText)


class AboutPage(Page):
    def __init__(self, paths: AppPaths, parent: QWidget | None = None) -> None:
        super().__init__(f"Sobre o {brand.BRAND}", parent=parent)
        logo = QLabel()
        pix = QPixmap(str(asset_path("vyonix_logo.svg")))
        if not pix.isNull():
            logo.setPixmap(pix.scaledToHeight(72, Qt.SmoothTransformation))
        else:
            logo.setText(brand.PRODUCT_NAME)
        self.body.addWidget(logo)

        frame, lay = card("Produto")
        for label, value in ((brand.PRODUCT_NAME, ""), ("Versão", __version__),
                             ("Etapa", __phase__), ("Slogan", brand.SLOGAN)):
            lbl = QLabel(f"<b>{label}</b>" + (f": {value}" if value else ""))
            lay.addWidget(lbl)
        self.body.addWidget(frame)

        self.body.addWidget(banner(f"<b>Aviso:</b> {brand.CLINICAL_DISCLAIMER}"))

        frame, lay = card("Pastas de dados")
        for label, path in (("Dados da máquina", paths.machine_root),
                            ("Dados do usuário", paths.user_root),
                            ("Banco de dados", paths.database_file)):
            lbl = QLabel(f"{label}: {path}")
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lbl.setWordWrap(True)
            lay.addWidget(lbl)
        self.body.addWidget(frame)

        frame, lay = card("Componentes de terceiros")
        for text in (f"Qt {QT_VERSION} / {QT_API} (Qt for Python) — LGPLv3", "SQLite — domínio público",
                     "Python — PSF License"):
            lay.addWidget(QLabel("•  " + text))
        self.body.addWidget(frame)
        self.body.addStretch(1)
