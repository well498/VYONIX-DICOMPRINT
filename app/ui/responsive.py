"""Responsividade da interface do DICOM Print (Prompt Mestre §14): nada cortado, sobreposto ou fora da tela.

* ``FlowLayout``: linha de botões/filtros que quebra para a linha seguinte quando falta largura
  (em vez de exigir rolagem horizontal em 1366 × 768 ou com escala de 125–150 %).
* ``ResponsiveFilter`` (instalado uma vez no ``QApplication``):
  - rótulos longos (``LONG_LABEL`` caracteres ou mais) passam a quebrar linha, salvo se marcados com a
    propriedade ``vyxNoWrap``;
  - listas suspensas deixam de impor a largura do item mais longo (a lista aberta continua mostrando o
    texto inteiro);
  - diálogos maiores que a área útil da tela ganham rolagem interna e são reposicionados dentro da tela.

Validado pela matriz ``tests/test_ui_matrix.py`` (11 configurações de resolução, escala e monitores).
"""

from __future__ import annotations

from app.ui.qt import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGroupBox,
                       QInputDialog, QLabel, QMessageBox, QSize, QSizePolicy, QVBoxLayout, QWidget, Qt, QtCore,
                       QtWidgets)

LONG_LABEL = 48
LONG_GROUP_TITLE = 40
COMBO_MIN_CHARS = 18
SCREEN_MARGIN = 24


class FlowLayout(QtWidgets.QLayout):
    """Layout em fluxo (exemplo oficial do Qt, adaptado): itens lado a lado, quebrando linha."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 8) -> None:
        super().__init__(parent)
        self._items: list = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # noqa: N802 - API Qt
        self._items.append(item)

    def addStretch(self, _stretch: int = 0) -> None:  # noqa: N802 - compatível com QHBoxLayout
        return None

    def addSpacing(self, _size: int) -> None:  # noqa: N802
        return None

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QtCore.QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        w = h = 0
        for item in self._items:
            s = item.sizeHint()
            w += s.width() + (self._spacing if w else 0)
            h = max(h, s.height())
        m = self.contentsMargins()
        return QSize(w + m.left() + m.right(), h + m.top() + m.bottom())

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect, *, test_only: bool) -> int:
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = eff.x(), eff.y(), 0
        for item in self._items:
            if item.widget() is not None and item.widget().isHidden():
                continue
            s = item.sizeHint()
            if x > eff.x() and x + s.width() > eff.right() + 1:
                x, y, line_h = eff.x(), y + line_h + self._spacing, 0
            if not test_only:
                item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), s))
            x += s.width() + self._spacing
            line_h = max(line_h, s.height())
        return y + line_h - rect.y() + m.bottom()


class ResponsiveGrid(QWidget):
    """Grade que muda o número de colunas conforme a largura disponível.

    ``items`` são ``(widget, span)`` pensados para ``max_cols`` colunas; com menos colunas o
    ``span`` é reduzido na mesma proporção e os itens seguem em fluxo, linha a linha. A largura
    mínima da grade é a de uma coluna — nunca força rolagem horizontal.
    """

    def __init__(self, min_col: int, max_cols: int, spacing: int = 14, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.min_col, self.max_cols = min_col, max_cols
        self.grid = QtWidgets.QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(spacing)
        self.grid.setSizeConstraint(QtWidgets.QLayout.SetNoConstraint)
        self._items: list[tuple[QWidget, int]] = []
        self.columns = 0

    def add(self, widget: QWidget, span: int = 1) -> None:
        self._items.append((widget, span))
        widget.setParent(self)
        self._arrange(force=True)

    def columns_for(self, width: int) -> int:
        spacing = self.grid.spacing()
        return max(1, min(self.max_cols, (width + spacing) // (self.min_col + spacing)))

    def _arrange(self, force: bool = False) -> None:
        cols = self.columns_for(self.width() or self.min_col * self.max_cols)
        if cols == self.columns and not force:
            return
        self.columns = cols
        for w, _ in self._items:
            self.grid.removeWidget(w)
        for c in range(self.max_cols):
            self.grid.setColumnStretch(c, 1 if c < cols else 0)
        row = col = 0
        for w, span in self._items:
            sp = max(1, min(cols, -(-span * cols // self.max_cols)))
            if col + sp > cols:
                row, col = row + 1, 0
            self.grid.addWidget(w, row, col, 1, sp)
            col += sp
            if col >= cols:
                row, col = row + 1, 0
        self.updateGeometry()

    def resizeEvent(self, event) -> None:  # noqa: N802 - API Qt
        super().resizeEvent(event)
        self._arrange()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        w = max((wd.minimumSizeHint().width() for wd, _ in self._items), default=0)
        return QSize(max(w, min(self.min_col, w or self.min_col)), super().minimumSizeHint().height())

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        cols = self.columns_for(width)
        spacing = self.grid.spacing()
        col_w = max(1, (width - spacing * (cols - 1)) // cols)
        total, row_h, col = 0, 0, 0
        for w, span in self._items:
            sp = max(1, min(cols, -(-span * cols // self.max_cols)))
            if col + sp > cols:
                total, row_h, col = total + row_h + spacing, 0, 0
            ww = col_w * sp + spacing * (sp - 1)
            h = w.heightForWidth(ww) if w.hasHeightForWidth() else -1
            row_h = max(row_h, h if h > 0 else w.sizeHint().height())
            col += sp
            if col >= cols:
                total, row_h, col = total + row_h + spacing, 0, 0
        return total + row_h


def fit_dialog(dlg: QDialog) -> bool:
    """Garante que o diálogo caiba na área útil da tela em que está. Retorna True se ajustou."""
    screen = dlg.screen()
    if screen is None:
        return False
    avail = screen.availableGeometry().adjusted(SCREEN_MARGIN // 2, SCREEN_MARGIN // 2,
                                                -SCREEN_MARGIN // 2, -SCREEN_MARGIN // 2)
    frame = dlg.frameGeometry()
    extra_w, extra_h = frame.width() - dlg.width(), frame.height() - dlg.height()
    want = dlg.sizeHint().expandedTo(dlg.size())
    squeezed = (dlg.layout() is not None and dlg.layout().minimumSize().height() > dlg.height() + 2)
    if (not squeezed and want.width() + extra_w <= avail.width()
            and want.height() + extra_h <= int(avail.height() * 0.92)):
        if not avail.contains(frame):
            dlg.move(max(avail.x(), min(frame.x(), avail.right() - frame.width())),
                     max(avail.y(), min(frame.y(), avail.bottom() - frame.height())))
        return False
    if not dlg.property("vyxScrollWrapped"):
        _wrap_in_scroll(dlg)
    dlg.setMinimumSize(QSize(min(dlg.minimumWidth(), avail.width() - extra_w), min(dlg.minimumHeight(),
                                                                                   avail.height() - extra_h)))
    w = min(want.width(), avail.width() - extra_w)
    h = min(want.height(), avail.height() - extra_h)
    dlg.resize(w, h)
    dlg.move(avail.x() + (avail.width() - w - extra_w) // 2, avail.y() + (avail.height() - h - extra_h) // 2)
    return True


def _wrap_in_scroll(dlg: QDialog) -> None:
    from app.ui.pages.base import FitScrollArea
    lay = dlg.layout()
    if lay is None:
        return
    buttons = [lay.itemAt(i).widget() for i in range(lay.count())
               if isinstance(lay.itemAt(i).widget(), QDialogButtonBox)]
    for b in buttons:
        lay.removeWidget(b)
    content = QWidget()
    content.setLayout(lay)            # o layout (e seus widgets) passa para o conteúdo rolável
    scroll = FitScrollArea()
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setWidget(content)
    outer = QVBoxLayout(dlg)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.addWidget(scroll, 1)
    for b in buttons:
        outer.addWidget(b)
    dlg.setProperty("vyxScrollWrapped", True)


class ResponsiveFilter(QtCore.QObject):
    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - API Qt
        t = event.type()
        if t in (QtCore.QEvent.Type.Polish, QtCore.QEvent.Type.Show):
            try:
                if t == QtCore.QEvent.Type.Polish and isinstance(obj, QWidget) and obj.layout() is not None:
                    _wrap_forms(obj.layout())
                if isinstance(obj, QGroupBox) and t == QtCore.QEvent.Type.Polish:
                    self._group(obj)
                if isinstance(obj, QLabel):
                    self._label(obj)
                elif isinstance(obj, QComboBox) and t == QtCore.QEvent.Type.Polish:
                    self._combo(obj)
                elif (t == QtCore.QEvent.Type.Show and isinstance(obj, QDialog)
                      and not isinstance(obj, (QMessageBox, QInputDialog, QFileDialog))):
                    fit_dialog(obj)
            except RuntimeError:          # objeto já destruído do lado C++
                pass
        return False

    @staticmethod
    def _label(lbl: QLabel) -> None:
        if lbl.wordWrap() or lbl.property("vyxNoWrap"):
            return
        pm = lbl.pixmap()
        if pm is not None and not pm.isNull():
            return
        text = lbl.text()
        if len(text) >= LONG_LABEL and "\n" not in text:
            lbl.setWordWrap(True)
            if lbl.sizePolicy().horizontalPolicy() == QSizePolicy.Fixed:
                lbl.setSizePolicy(QSizePolicy.Preferred, lbl.sizePolicy().verticalPolicy())

    @staticmethod
    def _group(box: QGroupBox) -> None:
        """Título longo de grupo não quebra linha e impõe largura: a explicação vai para um rótulo."""
        title = box.title()
        if box.property("vyxTitleSplit") or len(title) <= LONG_GROUP_TITLE:
            return
        for sep in (" — ", " - ", " ("):
            if sep in title:
                head, tail = title.split(sep, 1)
                break
        else:
            return
        tail = tail.strip().rstrip(")").strip()
        tail = tail[:1].upper() + tail[1:]
        lay = box.layout()
        note = QLabel(tail)
        note.setObjectName("muted")
        note.setWordWrap(True)
        if isinstance(lay, QFormLayout):
            lay.insertRow(0, note)
        elif isinstance(lay, QtWidgets.QBoxLayout):
            lay.insertWidget(0, note)
        else:
            note.deleteLater()
            return
        box.setTitle(head)
        box.setToolTip(title)
        box.setProperty("vyxTitleSplit", True)

    @staticmethod
    def _combo(combo: QComboBox) -> None:
        if combo.property("vyxKeepWidth"):
            return
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(COMBO_MIN_CHARS)


def _wrap_forms(layout) -> None:
    """Formulários quebram a linha (rótulo acima do campo) quando falta largura."""
    if isinstance(layout, QFormLayout):
        if layout.rowWrapPolicy() == QFormLayout.DontWrapRows:
            layout.setRowWrapPolicy(QFormLayout.WrapLongRows)
    for i in range(layout.count()):
        sub = layout.itemAt(i).layout()
        if sub is not None:
            _wrap_forms(sub)


def install(app) -> None:
    """Instala o filtro uma única vez por aplicação."""
    if app is None or app.property("vyxResponsive"):
        return
    flt = ResponsiveFilter(app)
    app.installEventFilter(flt)
    app.setProperty("vyxResponsive", True)
    app._vyx_responsive = flt          # mantém a referência viva
