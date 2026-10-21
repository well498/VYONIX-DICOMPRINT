"""Equipamentos → (equipamento) → Calibração de Imagem.

* Fonte: imagem recebida do equipamento (C-STORE), arquivo do computador (DICOM, JPG, PNG, BMP) ou
  padrão de teste gerado pelo VYONIX — abre mesmo sem nenhuma imagem recebida.
* Pré-visualização em tempo real **Original | Ajustada**, pelo mesmo pipeline da impressão (ajustes
  tonais em ponto flutuante + calibração da impressora do equipamento), em segundo plano.
* Matriz 3 × 3 de calibração, impressão, escolha da melhor combinação, rodadas progressivas, salvar no
  perfil do equipamento e reverter para a calibração anterior.
"""

from __future__ import annotations

from pathlib import Path

from app.core.contracts import PresentationParams
from app.core.errors import VyonixError
from app.imaging import tone
from app.imaging.calibration import CalibrationProfile
from app.printing import calibration_sheet as cs
from app.printing.paper import PAPER_LABELS
from app.ui.admin import current_actor, ensure_admin
from app.ui.images import to_pixmap
from app.ui.qt import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QGridLayout, QGroupBox,
                       QHBoxLayout, QKeySequence, QLabel, QMessageBox, QPushButton, QScrollArea, QShortcut, QSpinBox,
                       Qt, QTimer, QVBoxLayout, QWidget)
from app.ui.tone_control import ToneControl
from app.ui.widgets import fill_table, local_time, make_table, selected_key
from app.ui.workers import run_async

PATTERN = "pattern"
PREVIEW_SIDE = 1400


class ReceivedImageDialog(QDialog):
    """Imagens recebidas de um equipamento (identificação técnica, sem dados do paciente) com miniatura."""

    def __init__(self, parent, ctx, device_id: int | None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.chosen = None
        self.setWindowTitle("Imagem recebida do equipamento")
        self.resize(980, 520)
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        self.table = make_table(["Recebida em", "Equipamento", "Modalidade", "Quadros", "SOP Instance UID"])
        self.table.itemSelectionChanged.connect(self._thumb)
        self.table.doubleClicked.connect(lambda _: self._accept())
        left.addWidget(self.table)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        left.addWidget(bb)
        lay.addLayout(left, 3)
        self.thumb = QLabel("Selecione uma imagem")
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setMinimumSize(240, 240)
        lay.addWidget(self.thumb, 1)
        self.rows = ctx.imaging.recent_instances(limit=300, device_id=device_id)
        fill_table(self.table, [(local_time(r["received_at"]), r["device_name"] or r["source_ae"], r["modality"] or "—",
                                 r["number_of_frames"], r["sop_instance_uid"]) for r in self.rows],
                   [r["id"] for r in self.rows])
        if not self.rows:
            self.thumb.setText("Nenhuma imagem recebida deste equipamento.\nUse um arquivo ou o padrão de teste.")

    def _thumb(self) -> None:
        iid = selected_key(self.table)
        if iid is None:
            return
        self.thumb.setText("Carregando…")
        run_async(lambda: self.ctx.imaging.render(int(iid), PresentationParams(), max_side=240),
                  lambda r: self.thumb.setPixmap(to_pixmap(r.pixels, 240, 240)),
                  lambda exc: self.thumb.setText(f"Sem miniatura: {exc}"))

    def _accept(self) -> None:
        iid = selected_key(self.table)
        if iid is not None:
            self.chosen = int(iid)
            self.accept()


class DeviceCalibrationDialog(QDialog):
    def __init__(self, parent: QWidget, ctx, device_id: int | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Calibração de Imagem")
        self.resize(1320, 900)
        self.source = PATTERN
        self.source_label_text = "Padrão de teste do VYONIX"
        self.session = ctx.calibration.new_session()
        self.last_round: int | None = None
        self._seq = 0
        self._base_seq = 0
        self._busy = False
        self._pending = False
        self._original = None
        self._adjusted = None
        self._printer_cal = CalibrationProfile()
        root = QVBoxLayout(self)

        # ---------------------------------------------------- equipamento e fonte
        top = QHBoxLayout()
        top.addWidget(QLabel("Equipamento"))
        self.device = QComboBox()
        for d in ctx.devices.list():
            self.device.addItem(f"{d.name} ({d.ae_title}{' · ' + d.modality if d.modality else ''})", d.id)
        if device_id is not None:
            self.device.setCurrentIndex(max(self.device.findData(device_id), 0))
        top.addWidget(self.device, 2)
        top.addWidget(QLabel("Selecionar imagem para calibração"))
        self.src_kind = QComboBox()
        self.src_kind.addItem("Imagem padrão de teste", "pattern")
        self.src_kind.addItem("Receber de equipamento DICOM…", "received")
        self.src_kind.addItem("Abrir imagem do computador…", "file")
        top.addWidget(self.src_kind, 1)
        choose = QPushButton("Selecionar…")
        choose.clicked.connect(lambda _=False: self.choose_source())
        top.addWidget(choose)
        root.addLayout(top)
        self.src_info = QLabel(self.source_label_text)
        self.src_info.setObjectName("muted")
        root.addWidget(self.src_info)

        # ---------------------------------------------------- controles
        box = QGroupBox("Ajustes (escala −5,0 a +5,0 · 0,0 = neutro · setas ±0,5)")
        bl = QVBoxLayout(box)
        self.controls = {k: ToneControl(k) for k in ("brightness", "contrast", "gamma")}
        for c in self.controls.values():
            c.changed.connect(lambda _v: self._changed())
            bl.addWidget(c)
        row = QHBoxLayout()
        self.invert = QCheckBox("Inverter escala de cinza")
        self.invert.toggled.connect(lambda _: self._changed())
        row.addWidget(self.invert)
        row.addWidget(QLabel("Passo fino do campo numérico"))
        self.fine = QComboBox()
        for s in tone.FINE_STEPS:
            self.fine.addItem(tone.fmt(s).lstrip("+"), s)
        self.fine.setCurrentIndex(2)
        self.fine.currentIndexChanged.connect(lambda _: [c.set_fine_step(self.fine.currentData())
                                                         for c in self.controls.values()])
        row.addWidget(self.fine)
        row.addStretch(1)
        self.dirty = QLabel("")
        self.dirty.setObjectName("fieldError")
        row.addWidget(self.dirty)
        for text, slot in (("Restaurar ajustes", self.restore), ("Salvar no perfil do equipamento", self.save),
                           ("Reverter para calibração anterior", self.revert), ("Cancelar sem salvar", self.cancel)):
            b = QPushButton(text)
            if text.startswith("Salvar"):
                b.setObjectName("primary")
            b.clicked.connect(lambda _=False, f=slot: f())
            row.addWidget(b)
        bl.addLayout(row)
        root.addWidget(box)

        # ---------------------------------------------------- pré-visualização
        pv = QHBoxLayout()
        pv.addWidget(QLabel("Visualização"))
        self.view_mode = QComboBox()
        self.view_mode.addItem("Lado a lado (Original | Ajustada)", "side")
        self.view_mode.addItem("Antes/depois (alternar)", "toggle")
        self.view_mode.currentIndexChanged.connect(lambda _: self._show())
        pv.addWidget(self.view_mode)
        self.show_original = QPushButton("Mostrar original")
        self.show_original.setCheckable(True)
        self.show_original.toggled.connect(lambda _: self._show())
        pv.addWidget(self.show_original)
        pv.addWidget(QLabel("Zoom"))
        self.zoom = QComboBox()
        for label, val in (("Ajustar à janela", 0), ("50 %", 50), ("100 %", 100), ("200 %", 200)):
            self.zoom.addItem(label, val)
        self.zoom.currentIndexChanged.connect(lambda _: self._show())
        pv.addWidget(self.zoom)
        pv.addStretch(1)
        self.values = QLabel("")
        pv.addWidget(self.values)
        self.busy = QLabel("")
        self.busy.setObjectName("muted")
        pv.addWidget(self.busy)
        root.addLayout(pv)
        views = QHBoxLayout()
        self.left_title, self.left, self.left_scroll = self._view("Imagem Original")
        self.right_title, self.right, self.right_scroll = self._view("Imagem Ajustada")
        for t, s in ((self.left_title, self.left_scroll), (self.right_title, self.right_scroll)):
            col = QVBoxLayout()
            col.addWidget(t)
            col.addWidget(s, 1)
            views.addLayout(col, 1)
        root.addLayout(views, 1)

        # ---------------------------------------------------- matriz 3 × 3
        mx = QGroupBox("Teste de calibração 3 × 3 e calibração progressiva")
        ml = QGridLayout(mx)
        self.mode = QComboBox()
        for key, (_a, _b, label) in cs.MODES.items():
            self.mode.addItem(label, key)
        self.step = QComboBox()
        for s in cs.STEPS:
            self.step.addItem(tone.fmt(s).lstrip("+"), s)
        self.step.setCurrentIndex(2)
        self.printer = QComboBox()
        for p in ctx.printers.list():
            if p.available:
                self.printer.addItem(p.name, p.name)
        self.paper = QComboBox()
        for v in ("A4", "A3"):
            self.paper.addItem(PAPER_LABELS[v], v)
        ml.addWidget(QLabel("Comparar"), 0, 0)
        ml.addWidget(self.mode, 0, 1)
        ml.addWidget(QLabel("Incremento"), 0, 2)
        ml.addWidget(self.step, 0, 3)
        ml.addWidget(QLabel("Impressora"), 0, 4)
        ml.addWidget(self.printer, 0, 5)
        ml.addWidget(QLabel("Papel"), 0, 6)
        ml.addWidget(self.paper, 0, 7)
        prev = QPushButton("Pré-visualizar folha")
        prev.clicked.connect(lambda _=False: self.preview_sheet())
        go = QPushButton("GERAR E IMPRIMIR TESTE DE CALIBRAÇÃO — 9 IMAGENS")
        go.setObjectName("primary")
        go.clicked.connect(lambda _=False: self.print_sheet())
        ml.addWidget(prev, 1, 0, 1, 2)
        ml.addWidget(go, 1, 2, 1, 4)
        ml.addWidget(QLabel("Melhor imagem na folha impressa"), 2, 0, 1, 2)
        self.best = QSpinBox()
        self.best.setRange(1, 9)
        self.best.setValue(5)
        ml.addWidget(self.best, 2, 2)
        apply_best = QPushButton("Aplicar combinação escolhida")
        apply_best.clicked.connect(lambda _=False: self.apply_choice())
        ml.addWidget(apply_best, 2, 3, 1, 2)
        self.round_info = QLabel("Nenhuma folha impressa nesta sessão.")
        self.round_info.setObjectName("muted")
        self.round_info.setWordWrap(True)
        ml.addWidget(self.round_info, 2, 5, 1, 3)
        self.rounds = make_table(["Data/hora", "Rodada", "Modo", "Incremento", "Centro", "Escolhida", "Trabalho"],
                                 min_height=110)
        ml.addWidget(self.rounds, 3, 0, 1, 8)
        root.addWidget(mx)
        self.note = QLabel("A escolha visual na folha impressa não comprova qualidade diagnóstica.")
        self.note.setObjectName("muted")
        root.addWidget(self.note)

        # ---------------------------------------------------- teclado
        self.active = "brightness"
        for i, key in enumerate(("brightness", "contrast", "gamma"), start=1):
            QShortcut(QKeySequence(f"Ctrl+{i}"), self, activated=lambda k=key: self._activate(k))
        QShortcut(QKeySequence("Ctrl+Up"), self, activated=lambda: self._nudge(+1))
        QShortcut(QKeySequence("Ctrl+Down"), self, activated=lambda: self._nudge(-1))

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self._render_adjusted)
        self.device.currentIndexChanged.connect(lambda _: self._load_device())
        self._load_device()

    # ------------------------------------------------------------ util
    def _view(self, title: str):
        t = QLabel(f"<b>{title}</b>")
        lbl = QLabel("—")
        lbl.setAlignment(Qt.AlignCenter)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(lbl)
        sc.setMinimumHeight(300)
        return t, lbl, sc

    def device_id(self) -> int | None:
        return self.device.currentData()

    def current(self) -> tone.ToneControls:
        return tone.ToneControls(brightness=self.controls["brightness"].value(),
                                 contrast=self.controls["contrast"].value(),
                                 gamma=self.controls["gamma"].value(), invert=self.invert.isChecked())

    def _is_dirty(self) -> bool:
        return any(c.is_dirty() for c in self.controls.values()) or self.invert.isChecked() != self._saved_invert

    def _activate(self, key: str) -> None:
        self.active = key
        self.controls[key].spin.setFocus()

    def _nudge(self, direction: int) -> None:
        c = self.controls[self.active]
        c.set_value(tone.step_value(c.value(), direction))

    def _msg(self, text: str) -> None:
        self.round_info.setText(text)

    # ------------------------------------------------------------ carga
    def _load_device(self) -> None:
        did = self.device_id()
        t = self.ctx.device_settings.tone(did) if did else tone.ToneControls()
        for k, c in self.controls.items():
            c.set_saved(getattr(t, k))
        self._saved_invert = t.invert
        self.invert.blockSignals(True)
        self.invert.setChecked(t.invert)
        self.invert.blockSignals(False)
        # calibração da impressora usada por este equipamento (mesma da impressão)
        try:
            res = self.ctx.jobs.resolve_for(device_id=did, modality=None)
            self._printer_cal = CalibrationProfile.from_json(res.values.get("calibration"))
            printer = res.values.get("printer")
            if printer:
                self.printer.setCurrentIndex(max(self.printer.findData(printer), 0))
            if res.values.get("paper") in ("A4", "A3"):
                self.paper.setCurrentIndex(self.paper.findData(res.values["paper"]))
        except Exception:  # noqa: BLE001
            self._printer_cal = CalibrationProfile()
        self._load_rounds()
        self._render_original()
        self._changed()

    def _load_rounds(self) -> None:
        did = self.device_id()
        rows = self.ctx.calibration.rounds(did) if did else []
        fill_table(self.rounds, [(local_time(r["created_at"]), r["round_no"], cs.MODES[r["mode"]][2],
                                  tone.fmt(r["step"]).lstrip("+"), tone.ToneControls.from_values(r["center"]).label(),
                                  f"{r['chosen_index']:02d}" if r["chosen_index"] else "—", f"#{r['job_id']}")
                                 for r in rows], [r["id"] for r in rows])

    def choose_source(self) -> None:
        kind = self.src_kind.currentData()
        if kind == "pattern":
            self.source, self.source_label_text = PATTERN, "Padrão de teste do VYONIX"
        elif kind == "received":
            dlg = ReceivedImageDialog(self, self.ctx, self.device_id())
            if not dlg.exec() or dlg.chosen is None:
                return
            row = next(r for r in dlg.rows if r["id"] == dlg.chosen)
            self.source = dlg.chosen
            self.source_label_text = (f"Imagem recebida de {row['device_name'] or row['source_ae']} · "
                                      f"{row['modality'] or '—'} · {local_time(row['received_at'])} · "
                                      f"SOP {row['sop_instance_uid']}")
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Abrir imagem para calibração", str(Path.home()),
                                                  "Imagens (*.dcm *.jpg *.jpeg *.png *.bmp);;Todos os arquivos (*)")
            if not path:
                return
            from app.imaging import raster
            try:
                raster.kind_of(Path(path))
            except VyonixError as exc:
                QMessageBox.warning(self, "Arquivo incompatível", str(exc))
                return
            self.source, self.source_label_text = path, f"Arquivo: {path}"
        self.src_info.setText(self.source_label_text)
        self._render_original()
        self._changed()

    # ------------------------------------------------------------ renderização
    def _render_original(self) -> None:
        self._base_seq += 1
        seq = self._base_seq
        src = self.source
        self.left.setText("Carregando…")

        def done(r):
            if seq == self._base_seq:
                self._original = r.pixels
                self._show()

        def fail(exc):
            self.left.setText(f"Não foi possível abrir a imagem:\n{exc}")
            self.right.setText("—")
        run_async(lambda: self.ctx.imaging.render(src, PresentationParams(), max_side=PREVIEW_SIDE), done, fail)

    def _changed(self) -> None:
        t = self.current()
        self.values.setText(t.label())
        self.dirty.setText("● Alterações não salvas" if self._is_dirty() else "")
        self.timer.start()

    def _render_adjusted(self) -> None:
        if self._busy:
            self._pending = True
            return
        self._busy = True
        self._seq += 1
        seq = self._seq
        src, t, cal = self.source, self.current(), self._printer_cal
        self.busy.setText("Processando…")

        def work():
            r = self.ctx.imaging.render(src, t.to_params(), max_side=PREVIEW_SIDE)
            return self.ctx.imaging.calibrated(r.pixels, cal)

        def done(px):
            self._busy = False
            self.busy.setText("")
            if seq == self._seq:
                self._adjusted = px
                self._show()
            if self._pending:
                self._pending = False
                self._render_adjusted()

        def fail(exc):
            self._busy = False
            self.busy.setText("")
            self.right.setText(f"Falha no processamento:\n{exc}")
        run_async(work, done, fail)

    def _pix(self, arr, label: QLabel):
        if arr is None:
            return None
        z = self.zoom.currentData()
        if not z:
            vp = label.parentWidget()
            w = max(200, (vp.width() if vp else 600) - 8)
            h = max(200, (vp.height() if vp else 400) - 8)
            return to_pixmap(arr, w, h)
        pm = to_pixmap(arr)
        return pm.scaled(int(pm.width() * z / 100), int(pm.height() * z / 100), Qt.KeepAspectRatio,
                         Qt.SmoothTransformation)

    def _show(self) -> None:
        side = self.view_mode.currentData() == "side"
        self.left_scroll.setVisible(side)
        self.left_title.setVisible(side)
        self.show_original.setEnabled(not side)
        if side:
            pm = self._pix(self._original, self.left)
            if pm is not None:
                self.left.setPixmap(pm)
            pm = self._pix(self._adjusted, self.right)
            self.right_title.setText("<b>Imagem Ajustada</b>")
        else:
            original = self.show_original.isChecked()
            pm = self._pix(self._original if original else self._adjusted, self.right)
            self.right_title.setText("<b>Imagem Original (antes)</b>" if original else "<b>Imagem Ajustada (depois)</b>")
        if pm is not None:
            self.right.setPixmap(pm)

    def resizeEvent(self, event) -> None:  # noqa: N802 - API Qt
        super().resizeEvent(event)
        if self.zoom.currentData() == 0:
            self._show()

    # ------------------------------------------------------------ ações
    def restore(self) -> None:
        for c in self.controls.values():
            c.set_value(c._saved, emit=False)
        self.invert.setChecked(self._saved_invert)
        self._changed()

    def save(self) -> None:
        did = self.device_id()
        if did is None:
            QMessageBox.information(self, "Calibração", "Cadastre um equipamento antes de salvar a calibração.")
            return
        if not ensure_admin(self, self.ctx.access, "salvar a calibração do equipamento"):
            return
        new = self.current()
        old = self.ctx.device_settings.tone(did)
        if old != new and not old.is_neutral():
            if QMessageBox.question(self, "Substituir calibração",
                                    f"Substituir a calibração atual deste equipamento\n{old.label()}\npor\n"
                                    f"{new.label()}?\n\nA versão anterior fica guardada e pode ser restaurada.") \
                    != QMessageBox.Yes:
                return
        try:
            self.ctx.device_settings.save_tone(did, new, actor=current_actor(), reason="calibração de imagem")
        except VyonixError as exc:
            QMessageBox.warning(self, "Calibração", str(exc))
            return
        self._load_device()
        self._msg(f"Calibração salva no perfil do equipamento: {new.label()}.")

    def revert(self) -> None:
        did = self.device_id()
        if did is None or not ensure_admin(self, self.ctx.access, "reverter a calibração"):
            return
        try:
            self.ctx.device_settings.revert_calibration(did, actor=current_actor())
        except VyonixError as exc:
            QMessageBox.information(self, "Calibração", str(exc))
            return
        self._load_device()
        self._msg("Calibração anterior restaurada.")

    def cancel(self) -> None:
        if self._is_dirty() and QMessageBox.question(
                self, "Cancelar", "Descartar os ajustes não salvos?") != QMessageBox.Yes:
            return
        self.reject()

    def reject(self) -> None:
        self.timer.stop()
        super().reject()

    # ------------------------------------------------------------ matriz
    def _matrix(self) -> cs.Matrix:
        return cs.build_matrix(self.current(), self.mode.currentData(), self.step.currentData())

    def _device_text(self) -> tuple[str | None, str | None]:
        did = self.device_id()
        d = self.ctx.devices.get(did) if did else None
        return (d.name if d else None), (d.modality if d else None)

    def preview_sheet(self) -> None:
        try:
            m = self._matrix()
        except VyonixError as exc:
            QMessageBox.warning(self, "Teste de calibração", str(exc))
            return
        name, modality = self._device_text()
        src, cal, paper, printer = self.source, self._printer_cal, self.paper.currentData(), self.printer.currentData()

        def work():
            return cs.compose(m, lambda p, side: self.ctx.imaging.render(src, p, max_side=side), paper=paper,
                              orientation="landscape", dpi=100, calibration=cal,
                              info=cs.sheet_info(device=name, modality=modality, printer=printer, paper=paper))

        def show(page):
            dlg = QDialog(self)
            dlg.setWindowTitle("Pré-visualização da folha de calibração")
            dlg.resize(1200, 860)
            lay = QVBoxLayout(dlg)
            if m.notes:
                n = QLabel("; ".join(m.notes))
                n.setWordWrap(True)
                lay.addWidget(n)
            lbl = QLabel()
            lbl.setPixmap(to_pixmap(page.pixels, 1160, 780))
            lbl.setAlignment(Qt.AlignCenter)
            lay.addWidget(lbl, 1)
            bb = QDialogButtonBox(QDialogButtonBox.Close)
            bb.rejected.connect(dlg.reject)
            lay.addWidget(bb)
            dlg.exec()
        self.busy.setText("Montando folha…")
        run_async(work, lambda p: (self.busy.setText(""), show(p)),
                  lambda exc: (self.busy.setText(""), QMessageBox.warning(self, "Teste de calibração", str(exc))))

    def print_sheet(self) -> None:
        printer = self.printer.currentData()
        if not printer:
            QMessageBox.warning(self, "Teste de calibração", "Nenhuma impressora disponível.")
            return
        name, modality = self._device_text()
        try:
            rid, jid, m = self.ctx.calibration.print_round(
                device_id=self.device_id(), session_id=self.session, center=self.current(),
                mode=self.mode.currentData(), step=self.step.currentData(), source=self.source, printer=printer,
                paper=self.paper.currentData(), actor=current_actor(), device_name=name, modality=modality)
        except VyonixError as exc:
            QMessageBox.warning(self, "Teste de calibração", str(exc))
            return
        self.last_round = rid
        self._load_rounds()
        self._msg(f"Folha enviada (trabalho #{jid}). Compare as 9 imagens no papel, informe a melhor e clique em "
                  "\u201cAplicar combinação escolhida\u201d." + (" " + " ".join(m.notes) if m.notes else ""))

    def apply_choice(self) -> None:
        rid = self.last_round or selected_key(self.rounds)
        if rid is None:
            QMessageBox.information(self, "Calibração", "Imprima uma folha (ou selecione uma rodada) primeiro.")
            return
        try:
            chosen = self.ctx.calibration.choose(int(rid), self.best.value(), actor=current_actor())
        except VyonixError as exc:
            QMessageBox.warning(self, "Calibração", str(exc))
            return
        for k, c in self.controls.items():
            c.set_value(getattr(chosen, k), emit=False)
        self.invert.setChecked(chosen.invert)
        idx = self.step.currentIndex()
        if idx > 0:
            self.step.setCurrentIndex(idx - 1)        # próxima rodada mais fina
        self._load_rounds()
        self._changed()
        self._msg(f"Aplicada a imagem {self.best.value():02d}: {chosen.label()}. Gere outra folha com incremento "
                  f"{self.step.currentText()} para refinar ou salve no perfil do equipamento.")
