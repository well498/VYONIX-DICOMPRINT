# -*- mode: python ; coding: utf-8 -*-
# PyInstaller — VYONIX Platform (Core + DEPLOY), distribuição onedir.
#
#   cd web && npm install && npm run build && cd ..
#   python -m PyInstaller --noconfirm --clean VyonixPlatform.spec
#
# Resultado: dist/VyonixPlatform/{VyonixPlatform.exe, vyonix-deploy.exe, _internal/}
# Depois do PyInstaller o pipeline acrescenta pgsql/ (PostgreSQL 17) e VERSION.txt.
# Nunca inclui o License Manager, o License Server nem chaves privadas.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve()
WEB = ROOT / "web" / "dist"
if not (WEB / "index.html").exists():
    raise SystemExit("web/dist ausente: compile a interface (npm run build) antes do PyInstaller.")

datas = [
    (str(ROOT / "vyonix" / "db" / "migrations"), "vyonix/db/migrations"),
    (str(ROOT / "vyonix_deploy" / "wizard" / "index.html"), "vyonix_deploy/wizard"),
    (str(ROOT / "vyonix_deploy" / "wizard" / "app.js"), "vyonix_deploy/wizard"),
    (str(WEB), "web"),
] + collect_data_files("docx")          # python-docx: importação de modelos DOCX (VYONIX REPORT)
hidden = (collect_submodules("uvicorn") + collect_submodules("vyonix") + collect_submodules("vyonix_deploy")
          + collect_submodules("alembic") + collect_submodules("pydicom.encaps") + collect_submodules("pynetdicom") + collect_submodules("docx") + ["psycopg_binary", "sqlalchemy.dialects.postgresql.psycopg",
                                             "win32timezone", "win32serviceutil", "servicemanager"])
# pydicom e pynetdicom entram no pacote: o VYONIX PACS valida e lê DICOM e serve C-FIND/C-MOVE no Core
# (sem numpy; frames saem como estão).
excludes = ["PySide6", "PySide2", "tkinter", "numpy", "license_manager",
            "license_server", "vyonix_commercial.engine", "vyonix_commercial.billing", "vyonix_commercial.schema",
            "app.ui", "app.dicom", "app.service", "app.database", "app.printing", "pytest"]

a = Analysis([str(ROOT / "packaging" / "platform_launcher.py")], pathex=[str(ROOT)], datas=datas,
             hiddenimports=hidden, excludes=excludes, noarchive=False)
pyz = PYZ(a.pure)
common = dict(debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=True,
              icon=str(ROOT / "build" / "vyonix.ico") if (ROOT / "build" / "vyonix.ico").exists() else None)
core = EXE(pyz, a.scripts, [], exclude_binaries=True, name="VyonixPlatform", **common)
deploy = EXE(pyz, a.scripts, [], exclude_binaries=True, name="vyonix-deploy", **common)
coll = COLLECT(core, deploy, a.binaries, a.datas, strip=False, upx=False, name="VyonixPlatform")
