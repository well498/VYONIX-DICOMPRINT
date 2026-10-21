"""Servidor DICOM (§4): estado, controle e autoteste do Storage SCP; associações ativas."""

from __future__ import annotations

from app.core.contracts import ServiceState
from app.database.repositories.events_repo import Category, EventFilter
from app.dicom import scu, sop
from app.dicom.association_manager import SELFTEST_AE
from app.ui.admin import ensure_admin
from app.ui.pages.base import Page, banner, card
from app.ui.qt import QGridLayout, QLabel, QTimer, QWidget
from app.ui.widgets import button, button_row, fill_table, local_time, make_table, status_text
from app.ui.workers import run_async

_STATE = {
    ServiceState.RUNNING: ("Em execução", "ok"), ServiceState.STOPPED: ("Parado", "warn"),
    ServiceState.STARTING: ("Iniciando…", "warn"), ServiceState.STOPPING: ("Parando…", "warn"),
    ServiceState.ERROR: ("Erro", "err"), ServiceState.NOT_IMPLEMENTED: ("Não implementado", "muted"),
}


class ServerPage(Page):
    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__("Servidor DICOM",
                         "Recepção de imagens (Storage SCP) e impressão DICOM (Print SCP). Com o serviço Windows "
                         "instalado, os servidores rodam no serviço e esta tela os comanda.", parent)
        self.ctx = ctx
        self.status = banner("")
        self.status.hide()
        self.body.addWidget(self.status)

        grid = QGridLayout()
        grid.setSpacing(14)
        self.body.addLayout(grid)
        frame, lay = card("Storage SCP — recepção")
        self.state = QLabel("—")
        self.detail = QLabel("—")
        self.detail.setWordWrap(True)
        self.detail.setObjectName("muted")
        lay.addWidget(self.state)
        lay.addWidget(self.detail)
        lay.addLayout(button_row(button("Iniciar", self.start_scp, primary=True), button("Parar", self.stop_scp),
                                 button("Reiniciar", self.restart_scp), button("Testar (C-ECHO local)", self.selftest)))
        grid.addWidget(frame, 0, 0)

        frame, lay = card("Print SCP — impressão DICOM")
        self.p_state = QLabel("—")
        self.p_detail = QLabel("—")
        self.p_detail.setWordWrap(True)
        self.p_detail.setObjectName("muted")
        lay.addWidget(self.p_state)
        lay.addWidget(self.p_detail)
        lay.addLayout(button_row(button("Iniciar", self.start_print), button("Parar", self.stop_print),
                                 button("Reiniciar", self.restart_print),
                                 button("Testar (C-ECHO local)", self.selftest_print)))
        grid.addWidget(frame, 1, 0)

        frame, lay = card("Configuração aceita")
        self.caps = QLabel("—")
        self.caps.setWordWrap(True)
        lay.addWidget(self.caps)
        grid.addWidget(frame, 0, 1, 2, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        frame, lay = card("Destinos aceitos (Regras DICOM) e portas de escuta")
        self.routes = make_table(["Serviço", "Porta", "AE Title de destino", "Regra", "Restrições de origem",
                                  "Habilitada"], min_height=140)
        lay.addWidget(self.routes)
        hint = QLabel("O equipamento envia para o IP deste computador, a porta e o AE Title de destino. Novas portas "
                      "das regras são abertas automaticamente (Firewall do Windows: regra do VYONIX para redes "
                      "privadas e de domínio). Use Servidor → Testar para o autoteste C-ECHO.")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        lay.addWidget(hint)
        self.body.addWidget(frame)

        frame, lay = card("Associações ativas")
        self.assoc = make_table(["AE", "Endereço", "Equipamento", "Recebidas", "Duplicadas", "Falhas", "Duração (s)"],
                                min_height=120)
        lay.addWidget(self.assoc)
        self.body.addWidget(frame)

        frame, lay = card("Eventos DICOM recentes")
        self.recent = make_table(["Data/hora", "Nível", "Ação", "Mensagem"], min_height=220)
        lay.addWidget(self.recent)
        self.body.addWidget(frame, 1)

        self.timer = QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.refresh)

    # ---------------------------------------------------------------- dados
    def on_shown(self) -> None:
        self.refresh()
        self.timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        self.timer.stop()
        super().hideEvent(event)

    def refresh(self) -> None:
        def load():
            st = self.ctx.storage_scp.status()
            events = self.ctx.events.query(EventFilter(categories=(Category.DICOM, Category.SECURITY), limit=30))
            routes = self.ctx.devices.repo.routes("store") + self.ctx.devices.repo.routes("print")
            return (st, self.ctx.storage_scp.active_associations(), events, self.ctx.storage_scp.accepted_ts,
                    self.ctx.print_scp.status(), routes)
        run_async(load, self._render)

    def _render(self, data) -> None:
        st, assocs, events, ts, pst, routes = data
        rows = []
        for r in routes:
            port = r.effective_port(self.ctx.devices.default_port(r.service))
            restr = " · ".join(x for x in (f"Calling {r.calling_restriction}" if r.calling_restriction else "",
                                            f"IP {r.ip_address}" if r.ip_address else "") if x) or "qualquer origem"
            rows.append(("C-STORE" if r.service == "store" else "DICOM Print", port, r.called_ae, r.name, restr,
                         "Sim" if r.authorized else "Não"))
        fill_table(self.routes, rows)
        ptext, pstyle = _STATE[pst.state]
        status_text(self.p_state, ptext, pstyle)
        self.p_detail.setText(pst.detail or "—")
        text, style = _STATE[st.state]
        status_text(self.state, text, style)
        since = f" · desde {st.since.astimezone().strftime('%d/%m %H:%M')}" if st.since else ""
        self.detail.setText((st.detail or "—") + since)
        ts = ts or sop.UNCOMPRESSED
        self.caps.setText(f"{len(sop.IMAGE_STORAGE)} classes de imagem (CT, MR, CR, DX, US, MG, XA, RF, NM, PT, "
                          f"captura secundária) e C-ECHO.\nSintaxes de transferência: "
                          + ", ".join(sop.TRANSFER_SYNTAX_NAMES.get(t, t) for t in ts) + "."
                          + "\n\nImpressão DICOM: Basic Grayscale e Basic Color Print Management, Presentation LUT, "
                            "Printer (N-GET). Formatos STANDARD\\C,R de 1×1 a 8×8. Layout, orientação e cópias "
                            "pedidos pelo equipamento são respeitados; papel e impressora vêm dos perfis.")
        fill_table(self.assoc, [(a["calling_ae"], a["address"], a["device"] or "não cadastrado",
                                 a["received"], a["duplicates"], a["failures"], a["seconds"]) for a in assocs])
        fill_table(self.recent, [(local_time(e.ts), e.level, e.action, e.message) for e in events])

    # ---------------------------------------------------------------- ações
    def _msg(self, text: str, style: str) -> None:
        self.status.setText(text)
        self.status.setProperty("state", style)
        self.status.style().polish(self.status)
        self.status.show()

    def _run(self, action: str, fn) -> None:
        if not ensure_admin(self, self.ctx.access, action):
            return
        run_async(fn, lambda _: self.refresh(), lambda exc: self._msg(f"Falha: {exc}", "err"))

    def start_scp(self) -> None:
        self._run("iniciar o servidor DICOM", self.ctx.storage_scp.start)

    def stop_scp(self) -> None:
        self._run("parar o servidor DICOM", self.ctx.storage_scp.stop)

    def restart_scp(self) -> None:
        self._run("reiniciar o servidor DICOM", self.ctx.storage_scp.restart)

    def start_print(self) -> None:
        if not self.ctx.settings.get("dicom.print.enabled"):
            self._msg("O Print SCP está desativado em Configurações → DICOM — Impressão.", "warn")
            return
        self._run("iniciar o Print SCP", self.ctx.print_scp.start)

    def stop_print(self) -> None:
        self._run("parar o Print SCP", self.ctx.print_scp.stop)

    def restart_print(self) -> None:
        self._run("reiniciar o Print SCP", self.ctx.print_scp.restart)

    def selftest_print(self) -> None:
        bound = self.ctx.print_scp.bound
        if self.ctx.print_scp.status().state != ServiceState.RUNNING or not bound:
            self._msg("Inicie o Print SCP antes de testar.", "warn")
            return
        host = "127.0.0.1" if bound[0] in ("0.0.0.0", "") else bound[0]
        ae = self.ctx.settings.get("dicom.print.ae_title")
        run_async(lambda: scu.echo(host, bound[1], ae, calling_ae=SELFTEST_AE, timeout=5),
                  lambda r: self._msg(f"Autoteste C-ECHO do Print SCP: {r['detail']}.", "ok" if r["ok"] else "err"),
                  lambda exc: self._msg(f"Falha no autoteste: {exc}", "err"))

    def selftest(self) -> None:
        bound = self.ctx.storage_scp.bound
        if self.ctx.storage_scp.status().state != ServiceState.RUNNING or not bound:
            self._msg("Inicie o servidor antes de testar.", "warn")
            return
        host = "127.0.0.1" if bound[0] in ("0.0.0.0", "") else bound[0]
        ae = self.ctx.settings.get("dicom.storage.ae_title")
        run_async(lambda: scu.echo(host, bound[1], ae, calling_ae=SELFTEST_AE, timeout=5),
                  lambda r: self._msg(f"Autoteste C-ECHO: {r['detail']}.", "ok" if r["ok"] else "err"),
                  lambda exc: self._msg(f"Falha no autoteste: {exc}", "err"))
