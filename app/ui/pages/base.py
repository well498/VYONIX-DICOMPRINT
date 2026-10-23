"""Componentes comuns das páginas."""

from __future__ import annotations

from app.ui.qt import Qt, QtCore
from app.ui.qt import (QFrame, QLabel, QScrollArea, QSizePolicy, QVBoxLayout,
                               QWidget)


class FitScrollArea(QScrollArea):
    """Área rolável que respeita conteúdo com quebra de linha (altura dependente da largura).

    O ``QScrollArea`` padrão dimensiona o conteúdo pela ``minimumSizeHint``, calculada para uma
    largura que não é a real; com rótulos que quebram linha, o conteúdo recebia menos altura do que
    precisava e os widgets se sobrepunham (ex.: botões sobre a tabela de usuários do Reception).
    Aqui a altura mínima do conteúdo é recalculada para a largura visível a cada redimensionamento
    e a cada mudança de layout.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self._fitting = False

    def setWidget(self, widget: QWidget) -> None:  # noqa: N802 - API Qt
        super().setWidget(widget)
        widget.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - API Qt
        if obj is self.widget() and event.type() == QtCore.QEvent.Type.LayoutRequest:
            QtCore.QTimer.singleShot(0, self._fit)
        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:  # noqa: N802 - API Qt
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        w = self.widget()
        lay = w.layout() if w is not None else None
        if self._fitting or lay is None or not lay.hasHeightForWidth():
            return
        self._fitting = True
        try:
            width = max(self.viewport().width(), w.minimumSizeHint().width())
            need = lay.totalHeightForWidth(width)
            if need > 0 and w.minimumHeight() != need:
                w.setMinimumHeight(need)
        finally:
            self._fitting = False


class Page(QWidget):
    """Página com título, subtítulo e área de conteúdo rolável."""

    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = FitScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)

        inner = QWidget()
        scroll.setWidget(inner)
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(28, 22, 28, 22)
        self.body.setSpacing(14)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("pageTitle")
        self.body.addWidget(self.title_label)
        if subtitle:
            s = QLabel(subtitle)
            s.setObjectName("pageSubtitle")
            s.setWordWrap(True)
            self.body.addWidget(s)

    def on_shown(self) -> None:
        """Chamado quando a página passa a ser exibida."""


def card(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(6)
    lbl = QLabel(title)
    lbl.setObjectName("cardTitle")
    lbl.setWordWrap(True)
    lay.addWidget(lbl)
    return frame, lay


def banner(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("banner")
    lbl.setWordWrap(True)
    lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lbl


class PlaceholderPage(Page):
    """Funcionalidade ainda não implementada — identificada explicitamente (§23, item 7)."""

    def __init__(self, title: str, phase: str, planned: list[str],
                 parent: QWidget | None = None) -> None:
        super().__init__(title, parent=parent)
        self.body.addWidget(banner(
            f"<b>Não implementado nesta versão.</b> Previsto para a <b>{phase}</b>. "
            "Nenhuma operação desta área é simulada."))
        frame, lay = card("Escopo planejado")
        for item in planned:
            lbl = QLabel(f"•  {item}")
            lbl.setWordWrap(True)
            lay.addWidget(lbl)
        self.body.addWidget(frame)
        self.body.addStretch(1)
