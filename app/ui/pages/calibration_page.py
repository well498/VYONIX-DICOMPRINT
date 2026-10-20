"""Calibração de impressão (§7): pré-visualização em tempo real, perfis e associações."""

from __future__ import annotations

from pathlib import Path

from app.core.contracts import PresentationParams
from app.core.errors import SettingsValidationError, VyonixError
from app.devices.service import MODALITIES
from app.imaging.calibration import CalibrationProfile
from app.printing.profiles import PrintProfile
from app.services.imaging_service import PATTERN
from app.ui.admin import current_actor, ensure_admin
from app.ui.images import to_pixmap
from app.ui.pages.base import Page, banner
from app.ui.qt import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                       QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox,
                       Qt, QTimer, QVBoxLayout, QWidget)
from app.ui.widgets import fill_table, local_time, make_table
from app.ui.workers import run_async

PREVIEW_SIDE = 900


class _Slider(QWidget):
    """SpinBox com rótulo de valor, em unidades inteiras (ex.: 1.25 → 125 com scale=100)."""

    def __init__(self, lo: int, hi: int, scale: float, suffix: str = "", parent=None) -> None:
        super().__init__(parent)
        self.scale = scale
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.spin = QSpinBox()
        self.spin.setRange(lo, hi)
        self.spin.setSuffix(suffix)
        self.spin.setMinimumWidth(110)
        lay.addWidget(self.spin)
        lay.addStretch(1)

    def value(self) -> float:
        return self.spin.value() / self.scale

    def set(self, value: float) -> None:
        self.spin.setValue(round(value * self.scale))


class CalibrationPage(Page):
    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__("Calibração",
                         "Ajuste a resposta de cada impressora com o padrão de teste ou com uma imagem "
                         "recebida. As alterações aparecem na hora e ficam salvas em perfis.", parent)
        self.ctx = ctx
        self.body.addWidget(banner(
            "<b>Calibração visual.</b> Corrige brilho, contraste, gama e níveis de preto e branco "
            "observados no papel. Não substitui a calibração instrumental com densitômetro, que é um "
            "procedimento físico à parte; o VYONIX não declara conformidade com a curva GSDF (DICOM PS3.14)."))
        self.status = banner("")
        self.status.hide()
        self.body.addWidget(self.status)

        grid = QGridLayout()
        grid.setSpacing(14)
        self.body.addLayout(grid)

        # ---------------------------------------------------- pré-visualização
        prev = QGroupBox("Pré-visualização")
        pl = QVBoxLayout(prev)
        pics = QHBoxLayout()
        self.original = QLabel()
        self.adjusted = QLabel()
        for lbl in (self.original, self.adjusted):
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setMinimumSize(320, 300)
            pics.addWidget(lbl, 1)
        pl.addLayout(pics)
        self.compare = QCheckBox("Comparar original e ajustado lado a lado")
        self.compare.toggled.connect(lambda _: self._layout_preview())
        pl.addWidget(self.compare)
        self.applied = QLabel("")
        self.applied.setObjectName("muted")
        self.applied.setWordWrap(True)
        pl.addWidget(self.applied)
        grid.addWidget(prev, 0, 0, 3, 1)

        # ---------------------------------------------------- fonte
        src = QGroupBox("Imagem")
        sl = QFormLayout(src)
        self.source = QComboBox()
        self.source.currentIndexChanged.connect(lambda _: self._source_changed())
        sl.addRow("Fonte", self.source)
        row = QHBoxLayout()
        b = QPushButton("Abrir arquivo DICOM…")
        b.clicked.connect(self.open_file)
        row.addWidget(b)
        b = QPushButton("Atualizar lista")
        b.clicked.connect(self.load_sources)
        row.addWidget(b)
        sl.addRow("", self._wrap(row))
        self.frame = QSpinBox()
        self.frame.setRange(1, 1)
        self.frame.valueChanged.connect(lambda _: self._schedule(base=True))
        sl.addRow("Quadro", self.frame)
        self.rotate = QComboBox()
        for deg in (0, 90, 180, 270):
            self.rotate.addItem(f"{deg}°", deg)
        self.rotate.currentIndexChanged.connect(lambda _: self._schedule(base=True))
        sl.addRow("Rotação", self.rotate)
        grid.addWidget(src, 0, 1)

        # ---------------------------------------------------- calibração
        cal = QGroupBox("Calibração visual (salva no perfil)")
        cl = QFormLayout(cal)
        self.brightness = _Slider(-50, 50, 100, " %")
        self.contrast = _Slider(25, 300, 100, " %")
        self.gamma = _Slider(30, 300, 100)
        self.black = _Slider(0, 40, 100, " %")
        self.white = _Slider(60, 100, 100, " %")
        self.invert = QCheckBox("Inverter tons")
        for label, w in (("Brilho", self.brightness), ("Contraste", self.contrast), ("Gama (×100)", self.gamma),
                         ("Nível de preto", self.black), ("Nível de branco", self.white)):
            cl.addRow(label, w)
            w.spin.valueChanged.connect(lambda _: self._schedule())
        cl.addRow("", self.invert)
        self.invert.toggled.connect(lambda _: self._schedule())
        self.scale = _Slider(800, 1200, 10, " %")
        self.off_x = _Slider(-300, 300, 10, " mm")
        self.off_y = _Slider(-300, 300, 10, " mm")
        cl.addRow("Escala física (×10)", self.scale)
        cl.addRow("Deslocamento X (×10)", self.off_x)
        cl.addRow("Deslocamento Y (×10)", self.off_y)
        grid.addWidget(cal, 1, 1)

        # ---------------------------------------------------- perfil
        prof = QGroupBox("Perfil")
        fl = QFormLayout(prof)
        self.profile = QComboBox()
        self.profile.currentIndexChanged.connect(lambda _: self._profile_changed())
        fl.addRow("Perfil", self.profile)
        self.name = QLineEdit()
        fl.addRow("Nome", self.name)
        self.bindings = QLabel("—")
        self.bindings.setWordWrap(True)
        self.bindings.setObjectName("muted")
        fl.addRow("Associado a", self.bindings)
        buttons = QHBoxLayout()
        for text, slot in (("Salvar perfil", self.save_profile), ("Restaurar valores", self.restore),
                           ("Associar…", self.bind), ("Histórico", self.history)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            if text == "Salvar perfil":
                b.setObjectName("primary")
            buttons.addWidget(b)
        fl.addRow(self._wrap(buttons))
        self.print_test = QPushButton("Imprimir página de teste")
        self.print_test.setEnabled(False)
        self.print_test.setToolTip("Disponível com o gerenciamento de impressoras (Fase 4).")
        fl.addRow(self.print_test)
        grid.addWidget(prof, 2, 1)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)

        self._base = None          # imagem apresentada (antes da calibração)
        self._base_key = None
        self._loaded_profile: CalibrationProfile = CalibrationProfile()
        self._file: Path | None = None
        self._pending_base = False
        self._busy = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self._render)
        self._filling = False

    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        layout.setContentsMargins(0, 0, 0, 0)
        w.setLayout(layout)
        return w

    # ---------------------------------------------------------------- dados
    def on_shown(self) -> None:
        if self.source.count() == 0:
            self.load_sources()
        self.load_profiles()

    def load_sources(self) -> None:
        def fill(rows) -> None:
            current = self.source.currentData()
            self._filling = True
            self.source.clear()
            self.source.addItem("Padrão de teste (gerado pelo VYONIX)", PATTERN)
            for r in rows:
                label = (f"{local_time(r['received_at'])} · {r['modality'] or '—'} · "
                         f"{r['device_name'] or r['source_ae']}"
                         + (f" · {r['number_of_frames']} quadros" if r["number_of_frames"] > 1 else ""))
                self.source.addItem(label, ("instance", r["id"], r["number_of_frames"]))
            if self._file:
                self.source.addItem(f"Arquivo: {self._file.name}", ("file", str(self._file), 1))
            idx = self.source.findData(current) if current is not None else 0
            self.source.setCurrentIndex(max(idx, 0))
            self._filling = False
            self._source_changed()
        run_async(lambda: self.ctx.imaging.recent_instances(100), fill, self._error)

    def load_profiles(self, select_id: int | None = None) -> None:
        def fill(profiles) -> None:
            self._filling = True
            current = select_id if select_id is not None else self.profile.currentData()
            self.profile.clear()
            self.profile.addItem("— novo perfil —", None)
            self._profiles = {p.id: p for p in profiles}
            for p in profiles:
                self.profile.addItem(p.name, p.id)
            self.profile.setCurrentIndex(max(self.profile.findData(current), 0))
            self._filling = False
            self._profile_changed()
        run_async(self.ctx.profiles.list, fill, self._error)

    def open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Abrir arquivo DICOM", "", "DICOM (*.dcm *.DCM);;Todos (*)")
        if not path:
            return
        self._file = Path(path)
        try:
            frames = self.ctx.imaging.info(self._file).frames
        except VyonixError as exc:
            self._msg(str(exc), "err")
            return
        self.source.addItem(f"Arquivo: {self._file.name}", ("file", path, frames))
        self.source.setCurrentIndex(self.source.count() - 1)

    # ---------------------------------------------------------------- perfil
    def current_profile(self) -> CalibrationProfile:
        return CalibrationProfile(
            brightness=self.brightness.value(), contrast=self.contrast.value(), gamma=self.gamma.value(),
            invert=self.invert.isChecked(), black_level=self.black.value(), white_level=self.white.value(),
            scale_percent=self.scale.value(), offset_x_mm=self.off_x.value(), offset_y_mm=self.off_y.value())

    def _apply_profile_to_controls(self, p: CalibrationProfile) -> None:
        self._filling = True
        self.brightness.spin.setValue(round(p.brightness * 100))
        self.contrast.spin.setValue(round(p.contrast * 100))
        self.gamma.spin.setValue(round(p.gamma * 100))
        self.black.spin.setValue(round(p.black_level * 100))
        self.white.spin.setValue(round(p.white_level * 100))
        self.invert.setChecked(p.invert)
        self.scale.spin.setValue(round(p.scale_percent * 10))
        self.off_x.spin.setValue(round(p.offset_x_mm * 10))
        self.off_y.spin.setValue(round(p.offset_y_mm * 10))
        self._filling = False
        self._schedule()

    def _profile_changed(self) -> None:
        if self._filling:
            return
        pid = self.profile.currentData()
        p = getattr(self, "_profiles", {}).get(pid)
        self._loaded_profile = p.calibration if p else CalibrationProfile()
        self.name.setText(p.name if p else "")
        self._apply_profile_to_controls(self._loaded_profile)
        if pid is None:
            self.bindings.setText("—")
            return
        run_async(lambda: self.ctx.profiles.bindings(pid), self._show_bindings)

    def _show_bindings(self, rows) -> None:
        names = {"printer": "impressora", "device": "equipamento", "modality": "modalidade"}
        self.bindings.setText(", ".join(f"{names[r['scope_type']]} {r['scope_value']}" for r in rows) or "nenhuma associação")

    def restore(self) -> None:
        self._apply_profile_to_controls(self._loaded_profile)
        self._msg("Valores do perfil restaurados.", "muted")

    def save_profile(self) -> None:
        if not ensure_admin(self, self.ctx.access, "salvar perfil de calibração"):
            return
        pid = self.profile.currentData()
        base = getattr(self, "_profiles", {}).get(pid)
        profile = PrintProfile(**{**(base.__dict__ if base else {}), "id": pid, "name": self.name.text(),
                                  "calibration": self.current_profile()}) if base else \
            PrintProfile(id=None, name=self.name.text(), calibration=self.current_profile())
        try:
            saved = self.ctx.profiles.save(profile, actor=current_actor())
        except SettingsValidationError as exc:
            self._msg("; ".join(exc.errors.values()), "err")
            return
        self._msg(f"Perfil \"{saved.name}\" salvo.", "ok")
        self.load_profiles(select_id=saved.id)

    def bind(self) -> None:
        pid = self.profile.currentData()
        if pid is None:
            self._msg("Salve o perfil antes de associá-lo.", "warn")
            return
        if not ensure_admin(self, self.ctx.access, "associar perfil"):
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Associar perfil")
        form = QFormLayout(dlg)
        kind = QComboBox()
        kind.addItem("Modalidade", "modality")
        kind.addItem("Equipamento", "device")
        value = QComboBox()

        def fill_values() -> None:
            value.clear()
            if kind.currentData() == "modality":
                for code, name in MODALITIES:
                    value.addItem(f"{code} — {name}", code)
            else:
                for d in self.ctx.devices.list():
                    value.addItem(f"{d.name} ({d.ae_title})", str(d.id))
        kind.currentIndexChanged.connect(lambda _: fill_values())
        fill_values()
        form.addRow("Associar a", kind)
        form.addRow("Qual", value)
        note = QLabel("A associação a impressoras fica disponível com o gerenciamento de impressoras (Fase 4).")
        note.setObjectName("muted")
        note.setWordWrap(True)
        form.addRow(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec() and value.currentData() is not None:
            self.ctx.profiles.bind(pid, kind.currentData(), value.currentData(), actor=current_actor())
            self._msg("Associação salva.", "ok")
            run_async(lambda: self.ctx.profiles.bindings(pid), self._show_bindings)

    def history(self) -> None:
        pid = self.profile.currentData()
        if pid is None:
            return

        def show(rows) -> None:
            dlg = QDialog(self)
            dlg.setWindowTitle("Histórico do perfil")
            dlg.resize(820, 420)
            lay = QVBoxLayout(dlg)
            t = make_table(["Data/hora", "Usuário", "Valor anterior", "Novo valor"])
            fill_table(t, [(local_time(r.changed_at), r.changed_by, r.old_value or "", r.new_value or "") for r in rows])
            lay.addWidget(t)
            bb = QDialogButtonBox(QDialogButtonBox.Close)
            bb.rejected.connect(dlg.reject)
            lay.addWidget(bb)
            dlg.exec()
        run_async(lambda: self.ctx.changes.list(entity_type="print_profile", entity_id=str(pid)), show, self._error)

    # ---------------------------------------------------------------- render
    def _source_changed(self) -> None:
        if self._filling:
            return
        data = self.source.currentData()
        frames = data[2] if isinstance(data, tuple) else 1
        self.frame.setRange(1, max(1, frames))
        self._schedule(base=True)

    def _schedule(self, base: bool = False) -> None:
        if self._filling:
            return
        self._pending_base = self._pending_base or base
        self.timer.start()

    def _view_params(self) -> PresentationParams:
        return PresentationParams(frame_index=self.frame.value() - 1, rotate_degrees=self.rotate.currentData() or 0)

    def _render(self) -> None:
        if self._busy:
            self.timer.start()
            return
        data = self.source.currentData()
        if data is None:
            return
        source = PATTERN if data == PATTERN else (int(data[1]) if data[0] == "instance" else data[1])
        params = self._view_params()
        key = (source, params)
        profile = self.current_profile()
        try:
            profile.validate()
        except VyonixError as exc:
            self._msg(str(exc), "err")
            return
        need_base = self._pending_base or self._base is None or key != self._base_key
        self._pending_base = False
        base = self._base
        self._busy = True

        def work():
            b = self.ctx.imaging.render(source, params, max_side=PREVIEW_SIDE).pixels if need_base else base
            return b, self.ctx.imaging.calibrated(b, profile)

        def done(result) -> None:
            self._busy = False
            self._base, self._base_key = result[0], key
            self._last = result
            self._layout_preview()
            self.applied.setText(f"Perfil: brilho {profile.brightness:+.0%}, contraste {profile.contrast:.0%}, "
                                 f"gama {profile.gamma:.2f}, níveis {profile.black_level:.0%}–{profile.white_level:.0%}"
                                 + (", invertido" if profile.invert else ""))

        def fail(exc: BaseException) -> None:
            self._busy = False
            self._msg(str(exc) if isinstance(exc, VyonixError) else f"Falha ao renderizar: {exc}", "err")

        run_async(work, done, fail)

    def _layout_preview(self) -> None:
        last = getattr(self, "_last", None)
        if last is None:
            return
        base, adjusted = last
        if self.compare.isChecked():
            self.original.show()
            w, h = max(self.original.width(), 320), max(self.original.height(), 300)
            self.original.setPixmap(to_pixmap(base, w, h))
            self.adjusted.setPixmap(to_pixmap(adjusted, w, h))
        else:
            self.original.hide()
            w, h = max(self.adjusted.width(), 640), max(self.adjusted.height(), 480)
            self.adjusted.setPixmap(to_pixmap(adjusted, w, h))

    # ---------------------------------------------------------------- mensagens
    def _msg(self, text: str, style: str) -> None:
        self.status.setText(text)
        self.status.setProperty("state", style)
        self.status.style().polish(self.status)
        self.status.show()

    def _error(self, exc: BaseException) -> None:
        self._msg(f"Falha: {exc}", "err")
