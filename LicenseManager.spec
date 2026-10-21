# -*- mode: python ; coding: utf-8 -*-
# PyInstaller — VYONIX License Manager (executável PORTÁTIL de arquivo único).
#
#   python tools/make_icon.py ; python tools/make_version_info.py
#   python -m PyInstaller --noconfirm --clean LicenseManager.spec
#
# Resultado: dist/VYONIX_License_Manager.exe — funciona com duplo clique, sem Python e sem o
# VYONIX DICOM Print. O mesmo executável é distribuído pelo instalador opcional
# (installer/LicenseManager.iss). Nenhuma chave privada é embutida: as chaves ficam no banco do
# administrador, cifradas com a frase-senha.

from pathlib import Path

ROOT = Path(SPECPATH).resolve()
BUILD = ROOT / "build"
icon = BUILD / "vyonix_lm.ico"
if not icon.exists():
    icon = BUILD / "vyonix.ico"
version_file = BUILD / "version_info_lm.txt"

QT_DROP = ["PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
           "PySide6.QtPdf", "PySide6.QtSvgWidgets", "PySide6.QtWebSockets", "PySide6.QtDBus", "PySide6.QtMultimedia"]

a = Analysis(
    [str(ROOT / "packaging" / "lm_launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "tests", "app", "license_admin", "numpy", "PIL", "pydicom", "pynetdicom",
              "unittest.mock", "PySide2"] + QT_DROP,
    noarchive=False,
)

# O License Manager não depende do VYONIX DICOM Print e não leva chaves.
for name, *_ in a.pure:
    if name == "app" or name.startswith("app."):
        raise SystemExit(f"Módulo do VYONIX DICOM Print no License Manager: {name}")
for entry in a.datas:
    if entry[0].lower().endswith((".pem", ".key", ".vylic")):
        raise SystemExit(f"Arquivo proibido no License Manager: {entry[0]}")

import re
DROP = [re.compile(p, re.I) for p in (
    r"(^|/)opengl32sw\.dll$", r"(^|/)d3dcompiler_47\.dll$",
    r"(^|/)Qt6(Quick|Qml|Pdf|Network|OpenGL|VirtualKeyboard|SvgWidgets|Multimedia|Designer|WebSockets|DBus)\w*\.dll$",
    r"/plugins/imageformats/(?!qico)[^/]+$", r"/plugins/platforms/(?!qwindows|qoffscreen)[^/]+$",
    r"/plugins/(tls|networkinformation|generic|platforminputcontexts|qmltooling|multimedia|bearer|platformthemes)/",
    r"/translations/(?!qtbase_pt_BR|qt_pt_BR)[^/]+\.qm$")]
a.binaries = [e for e in a.binaries if not any(p.search(e[0].replace("\\", "/")) for p in DROP)]
a.datas = [e for e in a.datas if not any(p.search(e[0].replace("\\", "/")) for p in DROP)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="VYONIX_License_Manager",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    runtime_tmpdir=None,
    icon=str(icon) if icon.exists() else None,
    version=str(version_file) if version_file.exists() else None,
)
