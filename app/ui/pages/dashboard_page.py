"""Dashboard (§13) — todos os valores vêm de ``DashboardService``."""

from __future__ import annotations

from datetime import datetime

from app.ui.qt import QTimer
from app.ui.qt import QGridLayout, QHBoxLayout, QLabel, QWidget

from app.core.contracts import ServiceState
from app.services.dashboard_service import DashboardService, DashboardSnapshot
from app.ui.pages.base import Page, card
from app.ui.workers import run_async
from app.utils.timeutil import from_iso

REFRESH_MS = 5000

_STATE_TEXT = {
    ServiceState.NOT_IMPLEMENTED: ("Não implementado", "muted"),
    ServiceState.STOPPED: ("Parado", "warn"),
    ServiceState.STARTING: ("Iniciando", "warn"),
    ServiceState.RUNNING: ("Em execução", "ok"),
    ServiceState.STOPPING: ("Parando", "warn"),
    ServiceState.ERROR: ("Erro", "err"),
}
_ALERT_STYLE = {"info": "muted", "warning": "warn", "error": "err"}


def _local(ts: str) -> str:
    return from_iso(ts).astimezone().strftime("%d/%m/%Y %H:%M:%S")


class DashboardPage(Page):
    def __init__(self, service: DashboardService, parent: QWidget | None = None) -> None:
        super().__init__("Dashboard", "Visão geral da operação. Atualização automática a cada 5 s.",
                         parent)
        self.service = service
        self._busy = False

        grid = QGridLayout()
        grid.setSpacing(14)
        self.body.addLayout(grid)

        # Indicadores numéricos
        self.kpi: dict[str, QLabel] = {}
        for col, (key, title) in enumerate([
            ("received", "Trabalhos recebidos (24 h)"), ("queue", "Trabalhos em fila"),
            ("spooled", "Enviados à impressão (24 h)"), ("failed", "Falhas (24 h)"),
        ]):
            frame, lay = card(title)
            value = QLabel("—")
            value.setObjectName("cardValue")
            lay.addWidget(value)
            self.kpi[key] = value
            grid.addWidget(frame, 0, col)

        frame, self.services_lay = card("Serviços")
        grid.addWidget(frame, 1, 0, 1, 2)
        frame, self.dicom_lay = card("Configuração DICOM")
        grid.addWidget(frame, 1, 2, 1, 2)
        frame, self.devices_lay = card("Equipamentos")
        grid.addWidget(frame, 2, 0, 1, 2)
        frame, self.printer_lay = card("Impressora selecionada")
        grid.addWidget(frame, 2, 2, 1, 2)
        frame, self.alerts_lay = card("Alertas operacionais")
        grid.addWidget(frame, 3, 0, 1, 4)
        frame, self.failures_lay = card("Falhas recentes")
        grid.addWidget(frame, 4, 0, 1, 4)
        for c in range(4):
            grid.setColumnStretch(c, 1)

        self.updated = QLabel("")
        self.updated.setObjectName("muted")
        self.body.addWidget(self.updated)
        self.body.addStretch(1)

        self.timer = QTimer(self)
        self.timer.setInterval(REFRESH_MS)
        self.timer.timeout.connect(self.refresh)

    # ------------------------------------------------------------------
    def on_shown(self) -> None:
        self.refresh()
        self.timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 - API Qt
        self.timer.stop()
        super().hideEvent(event)

    def refresh(self) -> None:
        if self._busy:
            return
        self._busy = True
        run_async(self.service.snapshot, self._render, self._failed)

    def _failed(self, exc: BaseException) -> None:
        self._busy = False
        self.updated.setText(f"Falha ao atualizar: {exc}")

    def _render(self, s: DashboardSnapshot) -> None:
        self._busy = False
        self.kpi["received"].setText(str(s.jobs_received_24h))
        self.kpi["queue"].setText(str(s.jobs_in_queue))
        self.kpi["spooled"].setText(str(s.jobs_spooled_24h))
        self.kpi["failed"].setText(str(s.jobs_failed_24h))

        _clear(self.services_lay)
        for st in s.services:
            text, style = _STATE_TEXT[st.state]
            row = QHBoxLayout()
            row.addWidget(QLabel(st.name), 1)
            state = QLabel(text)
            state.setObjectName(style)
            row.addWidget(state)
            detail = QLabel(st.detail)
            detail.setObjectName("muted")
            row.addWidget(detail)
            self.services_lay.addLayout(row)

        _clear(self.dicom_lay)
        self._line(self.dicom_lay, "Recepção (Storage SCP)",
                   f"AE {s.storage_ae} · {s.storage_address}:{s.storage_port}")
        self._line(self.dicom_lay, "Impressão (Print SCP)",
                   f"AE {s.print_ae} · porta {s.print_port}" if s.print_enabled else "Desabilitado")

        _clear(self.devices_lay)
        self._line(self.devices_lay, "Cadastrados", str(s.devices_total))
        self._line(self.devices_lay, "Autorizados", str(s.devices_authorized))
        if s.recent_devices:
            for d in s.recent_devices:
                self._line(self.devices_lay, f"{d.name} ({d.ae_title})", _local(d.last_seen_at))
        else:
            self._muted(self.devices_lay, "Nenhum equipamento conectado nas últimas 24 h.")

        _clear(self.printer_lay)
        self.printer_lay.addWidget(QLabel(s.selected_printer))

        _clear(self.alerts_lay)
        for a in s.alerts:
            lbl = QLabel(a.text)
            lbl.setWordWrap(True)
            lbl.setObjectName(_ALERT_STYLE.get(a.level, "muted"))
            self.alerts_lay.addWidget(lbl)

        _clear(self.failures_lay)
        if s.recent_failures:
            for e in s.recent_failures:
                self._line(self.failures_lay, _local(e.ts), f"[{e.category}] {e.message}")
        else:
            self._muted(self.failures_lay, "Nenhuma falha nas últimas 24 h.")

        title = "Dashboard" + (f" — {s.site_name}" if s.site_name else "")
        self.title_label.setText(title)
        self.updated.setText("Atualizado às " + datetime.now().strftime("%H:%M:%S"))

    # ------------------------------------------------------------------
    @staticmethod
    def _line(lay, label: str, value: str) -> None:
        row = QHBoxLayout()
        left = QLabel(label)
        left.setObjectName("muted")
        row.addWidget(left)
        row.addStretch(1)
        right = QLabel(value)
        right.setWordWrap(True)
        row.addWidget(right)
        lay.addLayout(row)

    @staticmethod
    def _muted(lay, text: str) -> None:
        lbl = QLabel(text)
        lbl.setObjectName("muted")
        lay.addWidget(lbl)


def _clear(lay) -> None:
    """Remove o conteúdo dinâmico, preservando o título do cartão (item 0)."""
    while lay.count() > 1:
        item = lay.takeAt(1)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def _clear_layout(lay) -> None:
    while lay.count():
        item = lay.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())
    lay.deleteLater()
