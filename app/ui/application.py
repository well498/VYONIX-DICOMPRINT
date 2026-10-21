"""Inicialização da aplicação gráfica."""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

from app.ui.qt import (QT_API, QT_VERSION, QApplication, QIcon, QLockFile, QMessageBox, QPixmap,
                       QTimer, QtCore, exec_app, install_translations, prepare_application)

from app import __version__, brand
from app.core.errors import VyonixError
from app.utils.paths import resolve_paths
from app.utils.resources import asset_path


SHOW_REQUEST = "show.request"


def _make_tray(app, window, ctx):
    """Ícone na bandeja: estado dos serviços, abrir e sair."""
    from app.ui.qt import QMenu, QSystemTrayIcon
    tray = QSystemTrayIcon(QIcon(str(asset_path("vyonix_icon.svg"))), app)
    menu = QMenu()
    menu.addAction("Abrir o VYONIX", window.bring_to_front)
    status_action = menu.addAction("Estado: —")
    status_action.setEnabled(False)
    menu.addSeparator()

    def quit_app():
        window.quitting = True
        window.close()
        app.quit()
    menu.addAction("Sair do VYONIX", quit_app)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: window.bring_to_front()
                           if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)

    def update():
        try:
            states = ctx.runtime.service_statuses()
        except Exception:  # noqa: BLE001
            return
        bad = [s for s in states if s.state.value == "error"]
        running = [s for s in states if s.state.value == "running"]
        text = (f"{brand.PRODUCT_NAME}: " + ("; ".join(f"{s.name} com erro" for s in bad) if bad
                                            else f"{len(running)} serviço(s) em execução"))
        tray.setToolTip(text[:120])
        status_action.setText(text[:80])
    timer = QTimer(tray)
    timer.setInterval(5000)
    timer.timeout.connect(update)
    timer.start()
    update()
    tray.show()
    return tray


def run_ui(*, data_dir=None, log_level=None, console_log=False, smoke_test=False,
           report=None, tray_start=False) -> int:
    from app.main import (EXIT_ALREADY_RUNNING, EXIT_OK, EXIT_SMOKE_FAILED,
                          EXIT_STARTUP_ERROR, _write_report)

    QApplication.setApplicationName(brand.PRODUCT_NAME)
    QApplication.setOrganizationName(brand.BRAND)
    QApplication.setApplicationVersion(__version__)
    if QApplication.instance() is None:
        prepare_application()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    translations = install_translations(app)
    app.setWindowIcon(QIcon(str(asset_path("vyonix_icon.svg"))))

    def fail_dialog(text: str) -> None:
        if not smoke_test:
            QMessageBox.critical(None, brand.PRODUCT_NAME, text)

    # Uma única interface por usuário e pasta de dados.
    paths = resolve_paths(data_dir)
    paths.user_root.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(paths.user_root / "vyonix-ui.lock"))
    if not lock.tryLock(200):
        if not smoke_test:
            # Pede à instância em execução (talvez só na bandeja) que mostre a janela.
            request = paths.user_root / SHOW_REQUEST
            try:
                request.write_text("show", encoding="utf-8")
                for _ in range(25):
                    if not request.exists():
                        return EXIT_ALREADY_RUNNING
                    time.sleep(0.1)
                request.unlink(missing_ok=True)
            except OSError:
                pass
            QMessageBox.information(None, brand.PRODUCT_NAME,
                                    f"O {brand.PRODUCT_NAME} já está aberto nesta sessão.")
        _write_report(report, {"ok": False, "error": "already running"})
        return EXIT_ALREADY_RUNNING

    from app.bootstrap import bootstrap
    from app.ui import theme
    from app.ui.main_window import MainWindow

    try:
        ctx = bootstrap(data_dir=data_dir, role="ui", log_level=log_level, console_log=console_log)
    except VyonixError as exc:
        fail_dialog(f"Não foi possível iniciar o {brand.PRODUCT_NAME}.\n\n{exc}\n\n"
                    "Consulte os logs ou restaure um backup do banco de dados.")
        _write_report(report, {"ok": False, "error": str(exc)})
        lock.unlock()
        return EXIT_STARTUP_ERROR

    result: dict = {"ok": False}
    try:
        theme.apply_theme(app, ctx.settings.get("ui.theme"))
        from app.service import remote
        if not remote.attach(ctx):      # serviço Windows ausente/parado: servidores rodam nesta janela
            ctx.runtime.start()
        window = MainWindow(ctx)
        tray = None
        from app.ui.qt import QSystemTrayIcon
        if not smoke_test and QSystemTrayIcon.isSystemTrayAvailable():
            tray = _make_tray(app, window, ctx)
            window.hide_on_close = bool(ctx.settings.get("ui.close_to_tray")) or tray_start
            app.setQuitOnLastWindowClosed(not window.hide_on_close)
            ctx.settings.subscribe(lambda ch: "ui.close_to_tray" in ch and (
                setattr(window, "hide_on_close", bool(ch["ui.close_to_tray"])),
                app.setQuitOnLastWindowClosed(not ch["ui.close_to_tray"])))
        request = paths.user_root / SHOW_REQUEST
        request.unlink(missing_ok=True)
        poll = QTimer()
        poll.setInterval(700)

        def check_request():
            if request.exists():
                request.unlink(missing_ok=True)
                window.bring_to_front()
        poll.timeout.connect(check_request)
        poll.start()
        if not (tray_start and tray is not None):
            window.show_fitted()
            if not smoke_test:
                from app.ui.pages.license_page import maybe_show_activation
                QTimer.singleShot(400, lambda: maybe_show_activation(window, ctx))
        if smoke_test:
            QTimer.singleShot(300, lambda: _smoke(app, window, ctx, result, translations))
        code = exec_app(app)
        window.shutdown()
        if smoke_test:
            _write_report(report, result)
            return EXIT_OK if result.get("ok") else EXIT_SMOKE_FAILED
        return code
    finally:
        ctx.close()
        lock.unlock()


def _smoke(app: QApplication, window, ctx, result: dict, translations) -> None:
    """Roteiro automático executado dentro do executável real (sem equipamentos)."""
    from app.ui.main_window import MENU
    from app.ui.workers import wait_all

    checks: list[dict] = []

    def check(name: str, fn) -> None:
        started = time.perf_counter()
        try:
            detail = fn()
            checks.append({"name": name, "ok": True, "detail": detail,
                           "ms": round((time.perf_counter() - started) * 1000)})
        except Exception as exc:  # noqa: BLE001
            checks.append({"name": name, "ok": False, "error": f"{type(exc).__name__}: {exc}",
                           "trace": traceback.format_exc()[-2000:]})

    def settle() -> None:
        for _ in range(5):
            app.processEvents()
            wait_all(5000)
        app.processEvents()

    def assets() -> str:
        for name in ("vyonix_icon.svg", "vyonix_logo.svg"):
            if QPixmap(str(asset_path(name))).isNull():
                raise RuntimeError(f"recurso não carregado: {name}")
        if window.windowIcon().isNull():
            raise RuntimeError("ícone da janela ausente")
        return "ícone e logotipo carregados"

    def pages() -> str:
        if window.nav.count() != 12 or len(MENU) != 12:
            raise RuntimeError(f"menu com {window.nav.count()} itens")
        for row in range(window.nav.count()):
            window.nav.setCurrentRow(row)
            settle()
            if window.stack.currentIndex() != row:
                raise RuntimeError(f"página {MENU[row]} não exibida")
        return "12 páginas exibidas"

    def dashboard() -> str:
        snap = ctx.dashboard.snapshot()
        return f"serviços={len(snap.services)} alertas={len(snap.alerts)}"

    def settings_roundtrip() -> str:
        page = window.settings_page
        window.nav.setCurrentRow(MENU.index("Configurações"))
        settle()
        page.editors["site.name"].setText("Teste automatizado")
        page.save()
        settle()
        stored = ctx.settings.get("site.name")
        if stored != "Teste automatizado":
            raise RuntimeError(f"valor salvo incorreto: {stored!r}")
        page.editors["dicom.storage.ae_title"].setText("INVALIDO\\AE")
        page.save()
        settle()
        if page.errors["dicom.storage.ae_title"].isHidden():
            raise RuntimeError("erro de validação não exibido")
        if ctx.settings.get("dicom.storage.ae_title") != "VYONIX":
            raise RuntimeError("valor inválido foi gravado")
        return "salvar válido e rejeitar inválido"

    def themes() -> str:
        from app.ui import theme
        return ",".join(theme.apply_theme(app, m) for m in ("dark", "light"))

    def history() -> str:
        window.nav.setCurrentRow(MENU.index("Histórico"))
        settle()
        n = ctx.events.count()
        if n < 2:
            raise RuntimeError(f"apenas {n} eventos registrados")
        return f"{n} eventos"

    def dicom_server() -> str:
        from app.dicom import scu
        from app.dicom.association_manager import SELFTEST_AE
        st = ctx.storage_scp.status()
        if st.state.value != "running":
            raise RuntimeError(f"Storage SCP não está em execução: {st.state.value} {st.detail}")
        host, port = ctx.storage_scp.bound
        host = "127.0.0.1" if host in ("0.0.0.0", "") else host
        r = scu.echo(host, port, ctx.settings.get("dicom.storage.ae_title"), calling_ae=SELFTEST_AE,
                     timeout=10)
        if not r["ok"]:
            raise RuntimeError(f"autoteste C-ECHO falhou: {r['detail']}")
        return f"{st.detail}; C-ECHO {r['ms']} ms"

    def image_codecs() -> str:
        from app.imaging import selftest
        results = selftest.run()
        bad = {k: v for k, v in results.items() if v != "ok"}
        if bad:
            raise RuntimeError("; ".join(f"{k}: {v}" for k, v in bad.items()))
        return ", ".join(results)

    def calibration_preview() -> str:
        from app.core.contracts import PresentationParams
        from app.imaging.calibration import CalibrationProfile
        r = ctx.imaging.render("pattern", PresentationParams(), max_side=800)
        adj = ctx.imaging.calibrated(r.pixels, CalibrationProfile(gamma=1.5, black_level=0.05))
        if adj.shape != r.pixels.shape or (adj == r.pixels).all():
            raise RuntimeError("calibração não alterou a imagem")
        return f"padrão de teste {r.pixels.shape[1]}x{r.pixels.shape[0]} calibrado"

    def _wait_job(jid: int, done: tuple[str, ...], timeout: float = 90.0):
        import time
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            job = ctx.jobs.get_job(jid)
            if job.state.value in done or job.state.value == "failed":
                return job
            QApplication.processEvents()
            time.sleep(0.2)
        return ctx.jobs.get_job(jid)

    def print_scp() -> str:
        """Associação real com o Print SCP: N-GET Printer, N-CREATE Film Session/Film Box e N-DELETE.

        Não envia N-ACTION: o autoteste nunca imprime numa impressora real.
        """
        from pydicom.dataset import Dataset
        from pydicom.uid import generate_uid
        from pynetdicom import AE
        from app.dicom import print_model as pm
        from app.dicom.association_manager import SELFTEST_AE
        st = ctx.print_scp.status()
        if not ctx.settings.get("dicom.print.enabled"):
            return "desativado em Configurações (não verificado)"
        if st.state.value != "running":
            raise RuntimeError(f"Print SCP não está em execução: {st.state.value} {st.detail}")
        host, port = ctx.print_scp.bound
        host = "127.0.0.1" if host in ("0.0.0.0", "") else host
        ae = AE(ae_title=SELFTEST_AE)
        ae.add_requested_context(pm.GRAYSCALE_META)
        assoc = ae.associate(host, port, ae_title=ctx.settings.get("dicom.print.ae_title"))
        if not assoc.is_established:
            raise RuntimeError("associação de impressão recusada")
        try:
            status, printer = assoc.send_n_get([0x21100010], pm.PRINTER, pm.PRINTER_INSTANCE,
                                               meta_uid=pm.GRAYSCALE_META)
            fs_uid, fb_uid = generate_uid(), generate_uid()
            fs = Dataset()
            fs.NumberOfCopies = 1
            s1, _ = assoc.send_n_create(fs, pm.FILM_SESSION, fs_uid, meta_uid=pm.GRAYSCALE_META)
            fb = Dataset()
            fb.ImageDisplayFormat = "STANDARD\\2,2"
            ref = Dataset()
            ref.ReferencedSOPClassUID, ref.ReferencedSOPInstanceUID = pm.FILM_SESSION, fs_uid
            fb.ReferencedFilmSessionSequence = [ref]
            s2, rsp = assoc.send_n_create(fb, pm.FILM_BOX, fb_uid, meta_uid=pm.GRAYSCALE_META)
            s3 = assoc.send_n_delete(pm.FILM_SESSION, fs_uid, meta_uid=pm.GRAYSCALE_META)
        finally:
            assoc.release()
        codes = [getattr(x, "Status", None) for x in (status, s1, s2, s3)]
        if any(c != 0 for c in codes) or len(rsp.ReferencedImageBoxSequence) != 4:
            raise RuntimeError(f"respostas inesperadas: {codes}")
        return f"{st.detail}; Printer={printer.PrinterStatus}/{printer.PrinterStatusInfo}; film box 2×2 criado e removido"

    def print_pdf() -> str:
        from pathlib import Path
        from app.printing.backends.pdf import PDF_PRINTER
        jid = ctx.jobs.test_page(printer=PDF_PRINTER, actor="smoke-test")
        job = _wait_job(jid, ("completed",))
        if job.state.value != "completed":
            raise RuntimeError(f"trabalho #{jid} em '{job.state.label}': {job.state_reason}")
        size = Path(job.output_path).stat().st_size
        return f"trabalho #{jid} concluído; PDF de {size // 1024} KB ({job.page_count} página)"

    def windows_printers() -> str:
        if sys.platform != "win32":
            return "não aplicável fora do Windows"
        err = ctx.printers.backend_errors.get("windows")
        if err:
            raise RuntimeError(err)
        win = [p for p in ctx.printers.refresh() if p.backend == "windows"]
        names = [p.name for p in win]
        target = next((p for p in win if "print to pdf" in p.driver.lower() or p.name == "Microsoft Print to PDF"),
                      None)
        if target is None:
            return f"{len(win)} impressora(s) do Windows; \"Microsoft Print to PDF\" ausente — envio GDI não verificado"
        jid = ctx.jobs.test_page(printer=target.name, actor="smoke-test")
        job = _wait_job(jid, ("spooled", "completed"))
        if job.state.value not in ("spooled", "completed"):
            raise RuntimeError(f"envio para '{target.name}' falhou: {job.state_reason}")
        from pathlib import Path
        out = Path(job.output_path) if job.output_path else None
        import time
        for _ in range(100):
            if out and out.exists() and out.stat().st_size > 0:
                break
            time.sleep(0.2)
        if not out or not out.exists() or out.stat().st_size == 0:
            raise RuntimeError(f"spooler aceitou, mas o arquivo não foi gerado: {job.output_path}")
        return (f"{len(names)} impressora(s); página de teste via GDI/spooler em '{target.name}' gerou "
                f"{out.stat().st_size // 1024} KB (estado: {job.state.label})")

    def device_calibration() -> str:
        from app.imaging import tone
        from app.printing import calibration_sheet as cs
        from app.utils.fonts import print_font
        font = print_font(20)
        if not hasattr(font, "path"):
            raise RuntimeError("fonte das impressões (DejaVu Sans) ausente: textos sairiam sem acentos")
        for kind in ("header", "footer"):
            info = ctx.templates.info(kind)
            if info is None or not info.is_standard:
                raise RuntimeError(f"modelo {kind}.bmp ausente ou fora do padrão 3000 × 206")
        m = cs.build_matrix(tone.ToneControls(gamma=0.5), "gamma_contrast", 0.5)
        page = cs.compose(m, lambda p, side: ctx.imaging.render("pattern", p, max_side=side), paper="A4", dpi=72,
                          info=cs.sheet_info(device="autoteste", modality="CT", printer="—", paper="A4"))
        return (f"folha 3 × 3 {page.pixels.shape[1]}×{page.pixels.shape[0]} px; header/footer.bmp 3000 × 206; "
                f"fonte {Path(font.path).name}")

    def licensing() -> str:
        from vyonix_protocol import crypto, formats
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        k = Ed25519PrivateKey.generate()
        sig = crypto.sign_ed25519(k, b"vyonix")
        if not crypto.verify_ed25519(crypto.public_hex(k), b"vyonix", sig) or \
                crypto.verify_ed25519(crypto.public_hex(k), b"vyonix!", sig):
            raise RuntimeError("verificação Ed25519 incorreta")
        req = formats.parse_request(ctx.license.request_code())
        st = ctx.license.status(refresh=True)
        note = ""
        if ctx.license.enforced and not st.active:
            if not ctx.paths.isolated:
                raise RuntimeError(f"funções licenciadas suspensas ({st.state.label}); ative a licença ou inicie a "
                                   "demonstração antes do autoteste")
            st = ctx.license.start_demo(actor="smoke-test")     # pasta isolada: DEMO só deste autoteste
            note = "; DEMO iniciada na pasta isolada do autoteste"
        prof = ctx.license.profile()
        comps = ", ".join(k for k, v in prof.available.items() if v) or "nenhum"
        return (f"Ed25519 (cryptography) OK; solicitação {req['hardware_id']} / {req['installation_id'][:13]}…; "
                f"componentes: {comps}; estado {st.state.value}{note}")

    def logs() -> str:
        if not ctx.log_file.exists() or ctx.log_file.stat().st_size == 0:
            raise RuntimeError("arquivo de log vazio")
        json.loads(ctx.log_file.read_text(encoding="utf-8").splitlines()[0])
        return str(ctx.log_file.name)

    def translation() -> str:
        yes = QtCore.QCoreApplication.translate("QPlatformTheme", "&Yes")
        if yes.replace("&", "") != "Sim":
            raise RuntimeError(f"diálogos do Qt não traduzidos ('{yes}'); pasta: {translations}")
        return "botões padrão em português"

    def geometry() -> str:
        avail = app.primaryScreen().availableGeometry()
        frame = window.frameGeometry()
        if window.isMaximized():
            # Maximizada, o Windows deixa as bordas invisíveis alguns pixels fora da tela.
            return (f"maximizada ({frame.width()}x{frame.height()}) em tela útil "
                    f"{avail.width()}x{avail.height()}")
        if frame.width() > avail.width() or frame.height() > avail.height():
            raise RuntimeError(f"janela {frame.width()}x{frame.height()} maior que a tela "
                               f"{avail.width()}x{avail.height()}")
        return f"janela {frame.width()}x{frame.height()} em tela útil {avail.width()}x{avail.height()}"

    for name, fn in (("licenciamento", licensing), ("recursos visuais", assets), ("navegação", pages),
                     ("tradução do Qt", translation), ("tamanho da janela", geometry),
                     ("dashboard", dashboard), ("configurações", settings_roundtrip),
                     ("temas", themes), ("histórico", history), ("servidor DICOM", dicom_server),
                     ("codecs de imagem", image_codecs), ("calibração", calibration_preview),
                     ("impressão DICOM (Print SCP)", print_scp), ("impressão em PDF (fila)", print_pdf), ("impressoras do Windows", windows_printers),
                     ("calibração por equipamento", device_calibration),
                     ("logs", logs)):
        check(name, fn)

    result.update({
        "ok": all(c["ok"] for c in checks),
        "version": __version__,
        "frozen": bool(getattr(sys, "frozen", False)),
        "qt_api": QT_API, "qt_version": QT_VERSION,
        "python": sys.version.split()[0],
        "qt_platform": QApplication.platformName(),
        "data_dir": str(ctx.paths.machine_root),
        "checks": checks,
    })
    window.close()
    app.quit()
