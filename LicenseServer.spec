# -*- mode: python ; coding: utf-8 -*-
# PyInstaller — VYONIX License Server (executável de console, arquivo único).
#
#   python tools/make_version_info.py
#   python -m PyInstaller --noconfirm LicenseServer.spec
#
# Resultado: dist/VYONIX_License_Server.exe — servidor central de licenças (não vai às clínicas).
# Nenhuma chave privada é embutida: a chave de assinatura do servidor fica na pasta de dados,
# cifrada com frase-senha. Também roda a partir do código-fonte (python -m license_server).

from pathlib import Path

ROOT = Path(SPECPATH).resolve()
BUILD = ROOT / "build"
icon = BUILD / "vyonix_lm.ico"
if not icon.exists():
    icon = BUILD / "vyonix.ico"
version_file = BUILD / "version_info_ls.txt"

a = Analysis(
    [str(ROOT / "packaging" / "ls_launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "tests", "numpy", "PIL", "pydicom", "pynetdicom", "PySide6", "PySide2",
              "unittest.mock", "app.ui", "app.dicom", "app.printing", "app.imaging", "app.jobs", "app.reception",
              "license_manager.ui"],
    noarchive=False,
)

# Somente o protocolo, a gestão comercial e a verificação de licenças: nada do aplicativo clínico.
ALLOWED_APP = {"app", "app.brand", "app.core", "app.core.errors", "app.licensing", "app.licensing.keys",
               "app.licensing.online"}
for name, *_ in a.pure:
    if (name == "app" or name.startswith("app.")) and name not in ALLOWED_APP:
        raise SystemExit(f"Módulo do VYONIX DICOM Print no License Server: {name}")
for entry in a.datas:
    if entry[0].lower().endswith((".pem", ".key", ".vylic")):
        raise SystemExit(f"Arquivo proibido no License Server: {entry[0]}")

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="VYONIX_License_Server",
    debug=False,
    strip=False,
    upx=False,
    console=True,
    runtime_tmpdir=None,
    icon=str(icon) if icon.exists() else None,
    version=str(version_file) if version_file.exists() else None,
)
