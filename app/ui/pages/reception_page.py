"""VYONIX Reception: endereço do painel da recepção, situação do servidor e usuários/perfis."""

from __future__ import annotations

from app.core.errors import ValidationError
from app.security.users import ROLES
from app.ui.admin import current_actor, ensure_admin
from app.ui.pages.base import Page, banner, card
from app.ui.qt import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QInputDialog, QLabel, QLineEdit,
                       QMessageBox, Qt, QWidget)
from app.ui.widgets import button, button_row, fill_table, local_time, make_table, selected_key
from app.ui.workers import run_async


class ReceptionPage(Page):
    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__("VYONIX Reception",
                         "Painel da recepção no navegador (rede local, HTTPS, com login): pesquisa de exames, "
                         "impressão sob demanda, IMPRIMIR AGORA, prevenção de duplicidade, controle de retirada, "
                         "alertas e relatórios. As configurações técnicas ficam somente neste programa.", parent)
        self.ctx = ctx
        self.state = banner("")
        self.body.addWidget(self.state)
        frame, lay = card("Acesso")
        self.url = QLabel("—")
        self.url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.url.setWordWrap(True)
        lay.addWidget(self.url)
        lay.addLayout(button_row(button("Abrir no navegador", self.open_browser, primary=True),
                                 button("Copiar endereço", self.copy), stretch_at=2))
        note = QLabel("O certificado HTTPS é gerado por este computador: na primeira vez, o navegador pede para "
                      "confirmar a exceção de segurança. Para eliminar o aviso, instale um certificado da instituição "
                      "(cert.pem e key.pem) na pasta indicada. Não exponha o painel à internet: por padrão, só "
                      "endereços da rede local são aceitos (Configurações → VYONIX Reception).")
        note.setWordWrap(True)
        note.setObjectName("muted")
        lay.addWidget(note)
        self.body.addWidget(frame)
        frame, lay = card("Usuários e perfis")
        perfis = QLabel("<b>Administrador</b>: tudo, inclusive usuários · <b>Técnico</b>: configurações técnicas e "
                        "recepção · <b>Supervisor da recepção</b>: recepção, reimpressão, cancelamento de entrega e "
                        "relatórios · <b>Recepcionista</b>: pesquisa, impressão, IMPRIMIR AGORA e retirada.")
        perfis.setWordWrap(True)
        lay.addWidget(perfis)
        self.users = make_table(["Usuário", "Nome", "Perfil", "Ativo", "Último acesso"], min_height=220)
        lay.addWidget(self.users)
        lay.addLayout(button_row(button("Novo usuário…", self.new_user, primary=True),
                                 button("Alterar perfil…", self.role), button("Ativar / desativar", self.toggle),
                                 button("Redefinir senha…", self.reset), stretch_at=4))
        self.body.addWidget(frame)
        self.body.addStretch(1)

    def on_shown(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        def load():
            return self.ctx.users.list(), self.ctx.reception.url, self.ctx.reception.error
        run_async(load, self._render)

    def _render(self, data) -> None:
        users, url, err = data
        port = self.ctx.settings.get("reception.port")
        if not self.ctx.settings.get("reception.enabled"):
            self.state.setText("VYONIX Reception desativado em Configurações.")
            self.state.setProperty("state", "warn")
        elif url or self.ctx.reception.running:
            self.state.setText(f"VYONIX Reception em execução: <b>{url}</b>")
            self.state.setProperty("state", "ok")
        elif err:
            self.state.setText(f"VYONIX Reception não iniciou: {err}")
            self.state.setProperty("state", "err")
        else:
            self.state.setText("O VYONIX Reception é executado pelo serviço Windows do VYONIX (ou por esta janela, "
                               "quando o serviço não está instalado).")
            self.state.setProperty("state", "warn")
        self.state.style().polish(self.state)
        host = self.ctx.reception.public_host()
        self.address = url or f"https://{host}:{port}/"
        self.url.setText(f"Endereço para os computadores da recepção: <b>{self.address}</b><br>"
                         f"Certificado: {self.ctx.reception.tls_dir}")
        if not users:
            self.url.setText(self.url.text() + "<br><b>Crie pelo menos um usuário para acessar o painel.</b>")
        fill_table(self.users, [(u["username"], u["display_name"], ROLES[u["role"]], "Sim" if u["active"] else "Não",
                                 local_time(u["last_login_at"])) for u in users], [u["id"] for u in users])

    def open_browser(self) -> None:
        import webbrowser
        webbrowser.open(getattr(self, "address", ""))

    def copy(self) -> None:
        from app.ui.qt import QApplication
        QApplication.clipboard().setText(getattr(self, "address", ""))

    def _admin(self, action: str) -> bool:
        return ensure_admin(self, self.ctx.access, action)

    def _try(self, fn) -> None:
        try:
            fn()
        except ValidationError as exc:
            QMessageBox.warning(self, "Usuários", str(exc))
        self.refresh()

    def new_user(self) -> None:
        if not self._admin("criar usuário"):
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Novo usuário")
        form = QFormLayout(dlg)
        un, nm, pw = QLineEdit(), QLineEdit(), QLineEdit()
        pw.setEchoMode(QLineEdit.Password)
        role = QComboBox()
        for k, v in ROLES.items():
            role.addItem(v, k)
        role.setCurrentIndex(3)
        for label, w in (("Usuário", un), ("Nome", nm), ("Perfil", role), ("Senha provisória", pw)):
            form.addRow(label, w)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec():
            self._try(lambda: self.ctx.users.create(un.text(), nm.text(), role.currentData(), pw.text(),
                                                    actor=current_actor()))

    def role(self) -> None:
        uid = selected_key(self.users)
        if uid is None or not self._admin("alterar perfil"):
            return
        items = list(ROLES.values())
        v, ok = QInputDialog.getItem(self, "Perfil", "Novo perfil:", items, 3, False)
        if ok:
            self._try(lambda: self.ctx.users.update(uid, role=list(ROLES)[items.index(v)], actor=current_actor()))

    def toggle(self) -> None:
        uid = selected_key(self.users)
        if uid is None or not self._admin("ativar/desativar usuário"):
            return
        cur = next(u for u in self.ctx.users.list() if u["id"] == uid)
        self._try(lambda: self.ctx.users.update(uid, active=not cur["active"], actor=current_actor()))

    def reset(self) -> None:
        uid = selected_key(self.users)
        if uid is None or not self._admin("redefinir senha"):
            return
        pw, ok = QInputDialog.getText(self, "Redefinir senha", "Senha provisória (o usuário troca no painel):",
                                      QLineEdit.Password)
        if ok and pw:
            self._try(lambda: self.ctx.users.set_password(uid, pw, actor=current_actor(), must_change=True))
