"""Configurações → Identidade da Impressão (cabeçalho/rodapé BMP) e Backup do banco de dados."""

from __future__ import annotations

import os
from pathlib import Path

from app.core.errors import VyonixError
from app.printing import templates as tpl
from app.ui.admin import current_actor, ensure_admin
from app.ui.images import to_pixmap
from app.ui.qt import (QDialog, QDialogButtonBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QMessageBox,
                       QPushButton, Qt, QVBoxLayout, QWidget)
from app.ui.widgets import local_time
from app.ui.workers import run_async


class IdentityBox(QGroupBox):
    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__("Identidade da Impressão — artes do cabeçalho e do rodapé", parent)
        self.ctx = ctx
        lay = QVBoxLayout(self)
        info = QLabel(f"Arquivos únicos header.bmp e footer.bmp, {tpl.WIDTH} × {tpl.HEIGHT} px, BMP RGB 24 bits, fundo "
                      "branco — os mesmos para A4/A3, retrato/paisagem e todas as modalidades. No papel, a arte ocupa a "
                      "largura útil mantendo a proporção. Cada equipamento liga ou desliga cabeçalho e rodapé nas "
                      "configurações dele. Pasta: " + str(ctx.templates.dir))
        info.setWordWrap(True)
        info.setObjectName("muted")
        lay.addWidget(info)
        self.previews: dict[str, QLabel] = {}
        for kind in ("header", "footer"):
            label = tpl.LABELS[kind]
            row = QHBoxLayout()
            prev = QLabel("—")
            prev.setMinimumHeight(60)
            prev.setAlignment(Qt.AlignCenter)
            prev.setStyleSheet("border: 1px solid #999;")
            self.previews[kind] = prev
            row.addWidget(prev, 1)
            for text, slot in ((f"Alterar {label}", lambda k=kind: self.change(k)),
                               (f"Visualizar {label}", lambda k=kind: self.view(k)),
                               (f"Restaurar {label} Original", lambda k=kind: self.restore(k))):
                b = QPushButton(text)
                b.clicked.connect(lambda _=False, f=slot: f())
                row.addWidget(b)
            lay.addWidget(QLabel(f"<b>{label}</b>"))
            lay.addLayout(row)
        self.refresh()

    def refresh(self) -> None:
        for kind, lbl in self.previews.items():
            img, warning = self.ctx.templates.load(kind)
            if img is None:
                lbl.setText(warning)
                continue
            import numpy as np
            lbl.setPixmap(to_pixmap(np.asarray(img), 900, 62))

    def change(self, kind: str) -> None:
        if not ensure_admin(self, self.ctx.access, f"alterar {tpl.LABELS[kind].lower()}"):
            return
        path, _ = QFileDialog.getOpenFileName(self, f"Selecionar {tpl.LABELS[kind].lower()} (BMP)", str(Path.home()),
                                              "Bitmap (*.bmp)")
        if not path:
            return
        try:
            self.ctx.templates.install(kind, Path(path))
        except tpl.NeedsConversion as exc:
            if QMessageBox.question(self, "Converter para o padrão", str(exc) + "\n\nConverter agora?") != \
                    QMessageBox.Yes:
                return
            try:
                self.ctx.templates.install(kind, Path(path), convert=True)
            except VyonixError as exc2:
                QMessageBox.warning(self, "Arquivo recusado", str(exc2))
                return
        except VyonixError as exc:
            QMessageBox.warning(self, "Arquivo recusado", str(exc))
            return
        self.ctx.events.add(level="INFO", category="admin", action="identity.change",
                            message=f"{tpl.LABELS[kind]} BMP alterado.", actor=current_actor())
        self.refresh()

    def view(self, kind: str) -> None:
        img, warning = self.ctx.templates.load(kind)
        if img is None:
            QMessageBox.information(self, tpl.LABELS[kind], warning)
            return
        import numpy as np
        dlg = QDialog(self)
        dlg.setWindowTitle(f"{tpl.LABELS[kind]} — {tpl.WIDTH} × {tpl.HEIGHT} px")
        dlg.resize(1240, 260)
        lay = QVBoxLayout(dlg)
        lbl = QLabel()
        lbl.setPixmap(to_pixmap(np.asarray(img), 1200, 120))
        lbl.setStyleSheet("border: 1px solid #999;")
        lay.addWidget(lbl)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        dlg.exec()

    def restore(self, kind: str) -> None:
        if not ensure_admin(self, self.ctx.access, f"restaurar {tpl.LABELS[kind].lower()}"):
            return
        if QMessageBox.question(self, "Restaurar", f"Voltar o {tpl.LABELS[kind].lower()} ao modelo original (branco)? "
                                "A arte atual fica guardada como *.anterior.bmp.") != QMessageBox.Yes:
            return
        self.ctx.templates.restore_original(kind)
        self.refresh()


class BackupBox(QGroupBox):
    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__("Backup do banco de dados (equipamentos, perfis, regras, calibrações e histórico)", parent)
        self.ctx = ctx
        lay = QVBoxLayout(self)
        self.state = QLabel("—")
        self.state.setWordWrap(True)
        lay.addWidget(self.state)
        row = QHBoxLayout()
        for text, slot in (("Fazer backup agora", self.backup), ("Abrir pasta de backups", self.open_folder),
                           ("Como restaurar…", self.how_to_restore)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=slot: f())
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.refresh()

    def refresh(self) -> None:
        files = self.ctx.backups.list()
        if files:
            from datetime import datetime, timezone
            last = files[0]
            when = datetime.fromtimestamp(last.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            self.state.setText(f"{len(files)} backup(s). Último: {last.name} ({local_time(when)}). Backups automáticos "
                               "diários; os 14 mais recentes são mantidos.")
        else:
            self.state.setText("Nenhum backup ainda. O backup automático é diário.")

    def backup(self) -> None:
        if not ensure_admin(self, self.ctx.access, "fazer backup"):
            return
        run_async(lambda: self.ctx.backups.create(actor=current_actor(), label="manual"),
                  lambda p: (QMessageBox.information(self, "Backup", f"Backup criado e verificado:\n{p}"), self.refresh()),
                  lambda exc: QMessageBox.warning(self, "Backup", str(exc)))

    def open_folder(self) -> None:
        self.ctx.backups.dir.mkdir(parents=True, exist_ok=True)
        if hasattr(os, "startfile"):
            os.startfile(str(self.ctx.backups.dir))  # noqa: S606 - abre o Explorer na pasta de backups
        else:
            QMessageBox.information(self, "Backups", str(self.ctx.backups.dir))

    def how_to_restore(self) -> None:
        QMessageBox.information(
            self, "Restaurar backup",
            "A restauração substitui o banco inteiro e precisa que nenhum processo o esteja usando:\n\n"
            "1. Feche o VYONIX (menu do ícone na bandeja → Sair).\n"
            "2. No Prompt de Comando como administrador: sc stop VyonixDicomPrint\n"
            f"3. \"{Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'VYONIX' / 'DICOM Print' / 'Vyonix.exe'}\" "
            "--restore-backup \"<arquivo .db da pasta de backups>\"\n"
            "4. sc start VyonixDicomPrint e abra o VYONIX.\n\n"
            "O banco atual é guardado automaticamente antes da troca. Arquivos com versão mais nova ou corrompidos "
            "são recusados.")
