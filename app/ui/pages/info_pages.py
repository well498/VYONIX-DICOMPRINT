"""Páginas informativas: Licença e Sobre."""

from __future__ import annotations

from app.ui.qt import QT_API, QT_VERSION, Qt
from app.ui.qt import QPixmap
from app.ui.qt import QApplication, QHBoxLayout, QLabel, QPushButton, QWidget

from app import __phase__, __version__, brand
from app.ui.pages.base import Page, banner, card
from app.ui.workers import run_async
from app.utils.paths import AppPaths
from app.utils.resources import asset_path


class LicensePage(Page):
    """Licenciamento offline (Fase 8): código de solicitação, instalação do arquivo e situação."""

    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__("Licença", "Licenciamento offline: não há comunicação com a internet. Envie o código de "
                         "solicitação ao fornecedor e instale o arquivo de licença (.vylic) recebido.", parent)
        self.ctx = ctx
        self.state = banner("")
        self.body.addWidget(self.state)
        frame, lay = card("Situação")
        self.details = QLabel("—")
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.details)
        self.policy = QLabel("")
        self.policy.setObjectName("muted")
        self.policy.setWordWrap(True)
        lay.addWidget(self.policy)
        row = QHBoxLayout()
        for text, slot in (("Instalar licença…", self.install), ("Remover licença", self.remove)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=slot: f())
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.body.addWidget(frame)

        frame, lay = card("Solicitar licença")
        self.installation = QLabel("—")
        self.installation.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.installation)
        self.code = QLabel("")
        self.code.setWordWrap(True)
        self.code.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.code.setObjectName("muted")
        lay.addWidget(self.code)
        row = QHBoxLayout()
        for text, slot in (("Gerar código de solicitação", self.generate), ("Copiar código", self.copy),
                           ("Salvar em arquivo…", self.save_code)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=slot: f())
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        hint = QLabel("O código contém o ID desta instalação, um identificador do computador (hash, sem números de "
                      "série) e a versão. Nenhum dado de paciente.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.body.addWidget(frame)
        self.body.addStretch(1)

    def on_shown(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        def load():
            lic = self.ctx.license
            return lic.status(refresh=True), lic.license_data(), lic.policy_text(), \
                self.ctx.settings.get("system.installation_id")
        run_async(load, self._render)

    def _render(self, data) -> None:
        from app.licensing.license import FEATURE_LABELS
        st, lic, policy, inst = data
        labels = {"valid": "Licença válida", "not_activated": "Licença não ativada", "expired": "Licença vencida",
                  "invalid": "Licença inválida", "hardware_mismatch": "Licença de outro computador"}
        self.state.setText(f"<b>{labels.get(st.state.value, st.state.value)}.</b> {st.message}")
        self.state.setProperty("state", "ok" if st.state.value == "valid" else "warn")
        self.state.style().polish(self.state)
        if lic is not None:
            feats = ", ".join(FEATURE_LABELS.get(f, f) for f in lic.features) or "—"
            self.details.setText(
                f"<b>{lic.edition}</b> — {lic.licensee}" + (f" ({lic.document})" if lic.document else "")
                + f"<br>Licença {lic.license_id}, emitida em {lic.issued_at}"
                + (f", válida até {lic.expires_at}" if lic.expires_at else ", sem vencimento")
                + f"<br>Recursos: {feats}"
                + (f"<br>Equipamentos autorizados: até {lic.max_devices}" if lic.max_devices else ""))
        else:
            self.details.setText("Nenhuma licença válida instalada.")
        self.policy.setText(policy)
        self.installation.setText(f"ID da instalação: {inst}")

    def _admin(self, action: str) -> bool:
        from app.ui.admin import ensure_admin
        return ensure_admin(self, self.ctx.access, action)

    def generate(self) -> None:
        self.code.setText(self.ctx.license.request_code())

    def copy(self) -> None:
        if not self.code.text():
            self.generate()
        QApplication.clipboard().setText(self.code.text())

    def save_code(self) -> None:
        from app.ui.qt import QFileDialog
        if not self.code.text():
            self.generate()
        path, _ = QFileDialog.getSaveFileName(self, "Salvar código de solicitação",
                                              str(self.ctx.paths.exports_dir / "vyonix-solicitacao-licenca.txt"),
                                              "Texto (*.txt)")
        if path:
            from pathlib import Path
            Path(path).write_text(self.code.text() + "\n", encoding="utf-8")

    def install(self) -> None:
        from pathlib import Path
        from app.core.errors import VyonixError
        from app.ui.admin import current_actor
        from app.ui.qt import QFileDialog, QMessageBox
        if not self._admin("instalar licença"):
            return
        path, _ = QFileDialog.getOpenFileName(self, "Instalar licença", str(self.ctx.paths.exports_dir),
                                              "Licença VYONIX (*.vylic);;Todos os arquivos (*)")
        if not path:
            return
        try:
            st = self.ctx.license.install(Path(path).read_text(encoding="utf-8"), actor=current_actor())
        except (VyonixError, OSError, UnicodeDecodeError) as exc:
            QMessageBox.warning(self, "Licença recusada", str(exc))
            return
        QMessageBox.information(self, "Licença instalada", st.message)
        self.refresh()

    def remove(self) -> None:
        from app.ui.admin import current_actor
        from app.ui.qt import QMessageBox
        if not self._admin("remover licença"):
            return
        if QMessageBox.question(self, "Remover licença", "Remover a licença desta instalação?") != QMessageBox.Yes:
            return
        self.ctx.license.remove(actor=current_actor())
        self.refresh()


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
