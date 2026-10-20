# -*- mode: python ; coding: utf-8 -*-
# PyInstaller — VYONIX DICOM Print (distribuição onedir).
#
#   python tools/make_icon.py            # gera build/vyonix.ico e imagens do instalador
#   python tools/make_version_info.py    # gera build/version_info.txt a partir de app.__version__
#   python -m PyInstaller --noconfirm --clean Vyonix.spec
#
# Resultado: dist/Vyonix/Vyonix.exe
# A pasta license_admin/ (ferramenta de emissão e chave privada) NUNCA é incluída.

import os
import re
from pathlib import Path

ROOT = Path(SPECPATH).resolve()

# Ligação Qt: PySide6 (Qt 6). Requisito mínimo do produto: Windows 10 64 bits.
QT_BINDING, OTHER_BINDING = "PySide6", "PySide2"

# Distribuição enxuta (padrão; VYONIX_SLIM=0 desliga): remove componentes do Qt que o VYONIX não usa.
# A interface é Qt Widgets com renderização por software (raster): não usa OpenGL, Direct3D,
# ANGLE, QML/Quick, rede, PDF nem formatos de imagem além de SVG e ICO. Medição em
# docs/ANALISE_DESEMPENHO (relatório): -49% de disco e -26% de memória, sem perda de função.
SLIM = os.environ.get("VYONIX_SLIM", "1") != "0"
SLIM_DROP = [re.compile(p, re.I) for p in (
    r"(^|/)opengl32sw\.dll$",                       # OpenGL por software (~20 MB)
    r"(^|/)d3dcompiler_47\.dll$",                   # compilador de shaders Direct3D
    r"(^|/)lib(EGL|GLESv2)\.dll$",                  # ANGLE (OpenGL ES sobre Direct3D, Qt 5)
    # Qt 6: QML e rede são módulos opcionais. Qt 5: a biblioteca base do PySide2 (pyside2.abi3.dll)
    # depende do Qt5Qml, que depende do Qt5Network — esses dois ficam.
    (r"(^|/)Qt6(Quick|Qml|Pdf|Network|OpenGL|VirtualKeyboard|SvgWidgets|Multimedia|Designer|WebSockets|DBus)\w*\.dll$"
     if QT_BINDING == "PySide6" else
     r"(^|/)Qt5(Quick|QmlModels|QmlWorkerScript|Pdf|OpenGL|VirtualKeyboard|SvgWidgets|Multimedia|Designer|WebSockets|DBus)\w*\.dll$"),
    r"/plugins/imageformats/(?!qsvg|qico)[^/]+$",
    r"/plugins/platforms/(?!qwindows|qoffscreen)[^/]+$",
    r"/plugins/(tls|networkinformation|generic|platforminputcontexts|qmltooling|multimedia|bearer|platformthemes)/",
    r"/translations/(?!qtbase_pt_BR|qt_pt_BR)[^/]+\.qm$",
)]
SLIM_EXCLUDES = [f"{QT_BINDING}.{m}" for m in (
    "QtNetwork", "QtQml", "QtQuick", "QtOpenGL", "QtOpenGLWidgets", "QtPdf", "QtSvgWidgets",
    "QtWebSockets", "QtDBus")]
BUILD = ROOT / "build"
icon = BUILD / "vyonix.ico"
version_file = BUILD / "version_info.txt"

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / "assets"), "assets")],
    hiddenimports=[f"{QT_BINDING}.QtSvg"],    # renderização do logotipo/ícone SVG
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "tests", "license_admin", "unittest.mock",
              OTHER_BINDING, "shiboken6" if QT_BINDING == "PySide2" else "shiboken2"]
             + (SLIM_EXCLUDES if SLIM else []),
    noarchive=False,
)

# Defesa adicional: nada de license_admin ou de chaves no pacote.
for entry in list(a.datas):
    if "license_admin" in entry[0] or entry[0].lower().endswith((".pem", ".key")):
        raise SystemExit(f"Arquivo proibido no pacote: {entry[0]}")

if SLIM:
    removed = []

    def _keep(entry):
        dest = entry[0].replace("\\", "/")
        if any(p.search(dest) for p in SLIM_DROP):
            try:
                removed.append((dest, os.path.getsize(entry[1])))
            except OSError:
                removed.append((dest, 0))
            return False
        return True

    a.binaries = [e for e in a.binaries if _keep(e)]
    a.datas = [e for e in a.datas if _keep(e)]
    BUILD.mkdir(exist_ok=True)
    with open(BUILD / "slim_removed.txt", "w", encoding="utf-8") as fh:
        for dest, size in sorted(removed, key=lambda r: -r[1]):
            fh.write(f"{size}\t{dest}\n")
    print(f"VYONIX_SLIM ({QT_BINDING}): {len(removed)} arquivos removidos, "
          f"{sum(s for _, s in removed) / 1048576:.1f} MB")

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Vyonix",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(icon) if icon.exists() else None,
    version=str(version_file) if version_file.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Vyonix",
)
