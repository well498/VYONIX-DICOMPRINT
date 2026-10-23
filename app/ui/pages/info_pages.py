"""Página informativa: Sobre (a página Licença está em license_page.py)."""

from __future__ import annotations

from app.ui.qt import QT_API, QT_VERSION, Qt
from app.ui.qt import QPixmap
from app.ui.qt import QLabel, QLineEdit, QWidget

from app import __phase__, __version__, brand
from app.ui.pages.base import Page, banner, card
from app.utils.paths import AppPaths
from app.utils.resources import asset_path


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
            # caminho num campo somente leitura: não força a largura da página (um caminho não quebra
            # linha) e pode ser copiado inteiro
            lay.addWidget(QLabel(label))
            field = QLineEdit(str(path))
            field.setReadOnly(True)
            field.setCursorPosition(0)
            lay.addWidget(field)
        self.body.addWidget(frame)

        frame, lay = card("Componentes de terceiros")
        for text in (f"Qt {QT_VERSION} / {QT_API} (Qt for Python) — LGPLv3", "SQLite — domínio público",
                     "Python — PSF License", "pydicom / pynetdicom — MIT", "NumPy — BSD", "Pillow — HPND",
                     "DejaVu Sans (fonte das impressões) — licença Bitstream Vera/DejaVu (livre)"):
            lay.addWidget(QLabel("•  " + text))
        self.body.addWidget(frame)
        self.body.addStretch(1)
