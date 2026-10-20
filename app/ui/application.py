"""Inicialização da aplicação gráfica."""

from __future__ import annotations

import sys

from PySide6.QtCore import QLockFile
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from app import __version__, brand
from app.core.errors import VyonixError
from app.utils.paths import resolve_paths
from app.utils.resources import asset_path


def run_ui(*, data_dir=None, log_level=None, console_log=False) -> int:
    from app.main import EXIT_ALREADY_RUNNING, EXIT_STARTUP_ERROR

    QApplication.setApplicationName(brand.PRODUCT_NAME)
    QApplication.setOrganizationName(brand.BRAND)
    QApplication.setApplicationVersion(__version__)
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(asset_path("vyonix_icon.svg"))))

    # Uma única interface por usuário e pasta de dados.
    paths = resolve_paths(data_dir)
    paths.user_root.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(paths.user_root / "vyonix-ui.lock"))
    if not lock.tryLock(200):
        QMessageBox.information(None, brand.PRODUCT_NAME,
                                f"O {brand.PRODUCT_NAME} já está aberto nesta sessão.")
        return EXIT_ALREADY_RUNNING

    from app.bootstrap import bootstrap
    from app.ui import theme
    from app.ui.main_window import MainWindow

    try:
        ctx = bootstrap(data_dir=data_dir, role="ui", log_level=log_level, console_log=console_log)
    except VyonixError as exc:
        QMessageBox.critical(None, brand.PRODUCT_NAME,
                             f"Não foi possível iniciar o {brand.PRODUCT_NAME}.\n\n{exc}\n\n"
                             "Consulte os logs ou restaure um backup do banco de dados.")
        lock.unlock()
        return EXIT_STARTUP_ERROR

    try:
        theme.apply_theme(app, ctx.settings.get("ui.theme"))
        window = MainWindow(ctx)
        window.show()
        code = app.exec()
        window.shutdown()
        return code
    finally:
        ctx.close()
        lock.unlock()
