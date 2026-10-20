"""Inicialização da aplicação gráfica."""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox

from app import __version__, brand
from app.core.errors import VyonixError
from app.utils.paths import resolve_paths
from app.utils.resources import asset_path


def run_ui(*, data_dir=None, log_level=None, console_log=False, smoke_test=False,
           report=None) -> int:
    from app.main import (EXIT_ALREADY_RUNNING, EXIT_OK, EXIT_SMOKE_FAILED,
                          EXIT_STARTUP_ERROR, _write_report)

    QApplication.setApplicationName(brand.PRODUCT_NAME)
    QApplication.setOrganizationName(brand.BRAND)
    QApplication.setApplicationVersion(__version__)
    app = QApplication.instance() or QApplication(sys.argv[:1])
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
        window = MainWindow(ctx)
        window.show()
        if smoke_test:
            QTimer.singleShot(300, lambda: _smoke(app, window, ctx, result))
        code = app.exec()
        window.shutdown()
        if smoke_test:
            _write_report(report, result)
            return EXIT_OK if result.get("ok") else EXIT_SMOKE_FAILED
        return code
    finally:
        ctx.close()
        lock.unlock()


def _smoke(app: QApplication, window, ctx, result: dict) -> None:
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

    def logs() -> str:
        if not ctx.log_file.exists() or ctx.log_file.stat().st_size == 0:
            raise RuntimeError("arquivo de log vazio")
        json.loads(ctx.log_file.read_text(encoding="utf-8").splitlines()[0])
        return str(ctx.log_file.name)

    for name, fn in (("recursos visuais", assets), ("navegação", pages),
                     ("dashboard", dashboard), ("configurações", settings_roundtrip),
                     ("temas", themes), ("histórico", history), ("logs", logs)):
        check(name, fn)

    result.update({
        "ok": all(c["ok"] for c in checks),
        "version": __version__,
        "frozen": bool(getattr(sys, "frozen", False)),
        "qt_platform": QApplication.platformName(),
        "data_dir": str(ctx.paths.machine_root),
        "checks": checks,
    })
    window.close()
    app.quit()
