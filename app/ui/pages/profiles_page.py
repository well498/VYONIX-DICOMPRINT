"""Perfis de impressão (§7, §9): papel, layout, margens, cópias, anotações e associações.

A calibração do perfil é ajustada na página Calibração (com pré-visualização); aqui ela é
apenas exibida. Precedência na resolução: padrão do sistema < impressora < modalidade <
equipamento < regra automática < pedido DICOM Print < escolha manual.
"""

from __future__ import annotations

from app.core.errors import SettingsValidationError, VyonixError
from app.devices.service import MODALITIES
from app.imaging.calibration import CalibrationProfile
from app.printing.paper import LAYOUTS
from app.printing.profiles import PrintProfile
from app.ui.admin import current_actor, ensure_admin
from app.ui.pages.base import Page, banner
from app.ui.pages.printers_page import PAPER_CHOICES
from app.ui.qt import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                       QLineEdit, QSpinBox, QVBoxLayout, QWidget)
from app.ui.widgets import button, button_row, fill_table, local_time, make_table, selected_key, status_text
from app.ui.workers import run_async

SCOPE_LABELS = {"printer": "Impressora", "device": "Equipamento", "modality": "Modalidade"}


def _spin(lo: int, hi: int, special: str | None = "não definir") -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo - (1 if special else 0), hi)
    if special:
        s.setSpecialValueText(special)
    s.setValue(s.minimum())   # o QSpinBox começa em 0; "não definir" é o mínimo
    return s


class ProfileDialog(QDialog):
    def __init__(self, parent: QWidget, service, profile: PrintProfile | None) -> None:
        super().__init__(parent)
        self.service, self.profile, self.saved = service, profile, None
        self.setWindowTitle("Editar perfil" if profile else "Novo perfil")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit()
        self.description = QLineEdit()
        self.paper = QComboBox()
        self.paper.addItem("— não definir —", None)
        for v, label in PAPER_CHOICES:
            self.paper.addItem(label, v)
        self.orientation = QComboBox()
        for v, label in ((None, "— não definir —"), ("auto", "Automática"), ("portrait", "Retrato"),
                         ("landscape", "Paisagem")):
            self.orientation.addItem(label, v)
        self.layout_box = QComboBox()
        self.layout_box.addItem("— não definir —", None)
        for x in LAYOUTS:
            self.layout_box.addItem(x.replace("x", " × "), x)
        self.copies = _spin(1, 99)
        self.margins = {k: _spin(0, 60) for k in ("top", "right", "bottom", "left")}
        self.spacing = _spin(0, 30)
        margins_row = QHBoxLayout()
        for k, label in (("top", "Topo"), ("right", "Direita"), ("bottom", "Base"), ("left", "Esquerda")):
            margins_row.addWidget(QLabel(label))
            margins_row.addWidget(self.margins[k])
        mw = QWidget()
        mw.setLayout(margins_row)
        self.header = QLineEdit()
        self.footer = QLineEdit()
        self.dpi = QComboBox()
        for v, label in ((None, "— não definir —"), (150, "150 dpi"), (200, "200 dpi"), (300, "300 dpi"),
                         (600, "600 dpi")):
            self.dpi.addItem(label, v)
        self.flags = {}
        for key, label in (("exam_info", "Informações do exame"), ("page_numbers", "Numerar páginas"),
                           ("border", "Borda nas imagens"), ("patient_info", "Nome e ID do paciente (LGPD)")):
            c = QComboBox()
            c.addItem("— não definir —", None)
            c.addItem("Sim", True)
            c.addItem("Não", False)
            self.flags[key] = c
        form.addRow("Nome *", self.name)
        form.addRow("Descrição", self.description)
        form.addRow("Papel", self.paper)
        form.addRow("Orientação", self.orientation)
        form.addRow("Layout", self.layout_box)
        form.addRow("Cópias", self.copies)
        form.addRow("Margens (mm)", mw)
        form.addRow("Espaçamento (mm)", self.spacing)
        form.addRow("Resolução de saída", self.dpi)
        form.addRow("Texto do cabeçalho", self.header)
        form.addRow("Texto do rodapé", self.footer)
        for key, label in (("exam_info", "Informações do exame"), ("page_numbers", "Numeração de páginas"),
                           ("border", "Borda"), ("patient_info", "Dados do paciente")):
            form.addRow(label, self.flags[key])
        lay.addLayout(form)
        note = QLabel("Campos “não definir” herdam o valor de um perfil de menor precedência ou o padrão "
                      "do sistema. A calibração é ajustada na página Calibração.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.error = QLabel("")
        self.error.setObjectName("fieldError")
        self.error.setWordWrap(True)
        lay.addWidget(self.error)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        if profile:
            self._fill(profile)

    @staticmethod
    def _set(combo: QComboBox, value) -> None:
        combo.setCurrentIndex(max(combo.findData(value), 0))

    def _fill(self, p: PrintProfile) -> None:
        self.name.setText(p.name)
        self.description.setText(p.description or "")
        self._set(self.paper, p.paper_size)
        self._set(self.orientation, p.orientation)
        self._set(self.layout_box, p.layout)
        self.copies.setValue(p.copies or 0)
        m = p.margins or {}
        for k, w in self.margins.items():
            w.setValue(int(m[k]) if k in m else -1)
        self.spacing.setValue(int(m["spacing"]) if "spacing" in m else -1)
        a = p.annotations or {}
        self.header.setText(a.get("header_text", ""))
        self.footer.setText(a.get("footer_text", ""))
        self._set(self.dpi, a.get("dpi"))
        for k, c in self.flags.items():
            self._set(c, a.get(k))

    def _collect(self) -> PrintProfile:
        margins = {k: w.value() for k, w in self.margins.items() if w.value() >= 0}
        if margins and len(margins) < 4:
            raise SettingsValidationError({"margins": "Informe as quatro margens ou nenhuma."})
        if self.spacing.value() >= 0:
            margins["spacing"] = self.spacing.value()
        ann = {}
        if self.header.text().strip():
            ann["header_text"] = self.header.text().strip()
        if self.footer.text().strip():
            ann["footer_text"] = self.footer.text().strip()
        if self.dpi.currentData():
            ann["dpi"] = self.dpi.currentData()
        for k, c in self.flags.items():
            if c.currentData() is not None:
                ann[k] = c.currentData()
        base = self.profile
        return PrintProfile(
            id=base.id if base else None, name=self.name.text(), description=self.description.text() or None,
            paper_size=self.paper.currentData(), orientation=self.orientation.currentData(),
            layout=self.layout_box.currentData(), margins=margins or None,
            calibration=base.calibration if base else CalibrationProfile(),
            copies=self.copies.value() or None, annotations=ann or None)

    def _save(self) -> None:
        try:
            self.saved = self.service.save(self._collect(), actor=current_actor())
        except SettingsValidationError as exc:
            self.error.setText("; ".join(exc.errors.values()))
            return
        self.accept()


class ProfilesPage(Page):
    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__("Perfis de impressão",
                         "Um perfil reúne papel, layout, margens, cópias, anotações e calibração. Associe-o a "
                         "uma impressora, modalidade ou equipamento. Precedência: padrão do sistema < impressora "
                         "< modalidade < equipamento < escolha manual.", parent)
        self.ctx = ctx
        self.status = banner("")
        self.status.hide()
        self.body.addWidget(self.status)
        self.body.addLayout(button_row(
            button("Novo perfil", self.add, primary=True), button("Editar", self.edit),
            button("Associar…", self.bind), button("Remover associação", self.unbind),
            button("Desativar perfil", self.deactivate)))
        self.table = make_table(["Perfil", "Papel", "Orientação", "Layout", "Cópias", "Calibração", "Associações",
                                 "Alterado em"], min_height=240)
        self.table.doubleClicked.connect(lambda _: self.edit())
        self.body.addWidget(self.table, 1)
        lbl = QLabel("Associações")
        lbl.setObjectName("cardTitle")
        self.body.addWidget(lbl)
        self.bindings = make_table(["Tipo", "Valor", "Perfil"], min_height=160)
        self.body.addWidget(self.bindings)
        self.profiles = {}
        self.binding_rows = []

    def on_shown(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        def load():
            return self.ctx.profiles.list(), self.ctx.profiles.bindings(), {d.id: d.name for d in
                                                                           self.ctx.devices.list(include_inactive=True)}
        run_async(load, self._render, self._error)

    def _render(self, data) -> None:
        profiles, bindings, devices = data
        self.profiles = {p.id: p for p in profiles}
        by_profile: dict[int, list[str]] = {}
        for b in bindings:
            by_profile.setdefault(b["profile_id"], []).append(self._binding_label(b, devices))
        orient = {"auto": "Automática", "portrait": "Retrato", "landscape": "Paisagem"}
        rows = [(p.name, p.paper_size or "—", orient.get(p.orientation, "—"), p.layout or "—", p.copies or "—",
                 "padrão" if p.calibration.is_identity() else "ajustada", "; ".join(by_profile.get(p.id, [])) or "—",
                 local_time(p.updated_at)) for p in profiles]
        fill_table(self.table, rows, [p.id for p in profiles])
        self.binding_rows = bindings
        fill_table(self.bindings, [(SCOPE_LABELS[b["scope_type"]], self._binding_label(b, devices, short=True),
                                    b["profile_name"]) for b in bindings], list(range(len(bindings))))

    @staticmethod
    def _binding_label(b, devices, short=False) -> str:
        value = b["scope_value"]
        if b["scope_type"] == "device":
            value = devices.get(int(value), f"equipamento {value}")
        return value if short else f"{SCOPE_LABELS[b['scope_type']]}: {value}"

    def _error(self, exc: BaseException) -> None:
        self._msg(f"Falha: {exc}", "err")

    def _msg(self, text: str, style: str) -> None:
        status_text(self.status, text, "banner")
        self.status.setProperty("state", style)
        self.status.style().polish(self.status)
        self.status.show()

    def _selected(self):
        p = self.profiles.get(selected_key(self.table))
        if p is None:
            self._msg("Selecione um perfil na lista.", "warn")
        return p

    def add(self) -> None:
        if not ensure_admin(self, self.ctx.access, "criar perfil"):
            return
        dlg = ProfileDialog(self, self.ctx.profiles, None)
        if dlg.exec():
            self._msg(f"Perfil “{dlg.saved.name}” criado.", "ok")
            self.refresh()

    def edit(self) -> None:
        p = self._selected()
        if p is None or not ensure_admin(self, self.ctx.access, "editar perfil"):
            return
        dlg = ProfileDialog(self, self.ctx.profiles, p)
        if dlg.exec():
            self._msg("Perfil salvo.", "ok")
            self.refresh()

    def bind(self) -> None:
        p = self._selected()
        if p is None or not ensure_admin(self, self.ctx.access, "associar perfil"):
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Associar “{p.name}”")
        form = QFormLayout(dlg)
        kind = QComboBox()
        for k, label in SCOPE_LABELS.items():
            kind.addItem(label, k)
        value = QComboBox()

        def fill_values() -> None:
            value.clear()
            if kind.currentData() == "modality":
                for code, name in MODALITIES:
                    value.addItem(f"{code} — {name}", code)
            elif kind.currentData() == "device":
                for d in self.ctx.devices.list():
                    value.addItem(f"{d.name} ({d.ae_title})", str(d.id))
            else:
                for pr in self.ctx.printers.list():
                    value.addItem(pr.name, pr.name)
        kind.currentIndexChanged.connect(lambda _: fill_values())
        fill_values()
        form.addRow("Associar a", kind)
        form.addRow("Qual", value)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec() and value.currentData() is not None:
            try:
                self.ctx.profiles.bind(p.id, kind.currentData(), value.currentData(), actor=current_actor())
            except VyonixError as exc:
                self._msg(str(exc), "err")
                return
            self._msg("Associação salva (substitui a associação anterior do mesmo item).", "ok")
            self.refresh()

    def unbind(self) -> None:
        idx = selected_key(self.bindings)
        if idx is None or idx >= len(self.binding_rows):
            self._msg("Selecione uma associação na tabela de associações.", "warn")
            return
        if not ensure_admin(self, self.ctx.access, "remover associação"):
            return
        b = self.binding_rows[idx]
        self.ctx.profiles.unbind(b["scope_type"], b["scope_value"], actor=current_actor())
        self._msg("Associação removida.", "ok")
        self.refresh()

    def deactivate(self) -> None:
        p = self._selected()
        if p is None or not ensure_admin(self, self.ctx.access, "desativar perfil"):
            return
        self.ctx.profiles.deactivate(p.id, actor=current_actor())
        self._msg(f"Perfil “{p.name}” desativado e associações removidas.", "ok")
        self.refresh()
