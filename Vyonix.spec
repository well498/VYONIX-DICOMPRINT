# -*- mode: python ; coding: utf-8 -*-
# PyInstaller — VYONIX DICOM Print (distribuição onedir).
#
#   python tools/make_icon.py            # gera build/vyonix.ico e imagens do instalador
#   python tools/make_version_info.py    # gera build/version_info.txt a partir de app.__version__
#   python -m PyInstaller --noconfirm --clean Vyonix.spec
#
# Resultado: dist/Vyonix/Vyonix.exe
# O VYONIX License Manager (license_manager/) e qualquer chave privada NUNCA são incluídos.

import os
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

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

# Decodificadores/codificadores de Pixel Data são carregados dinamicamente pelo pydicom; o
# pylibjpeg descobre o openjpeg por entry points (exige os metadados do pacote).
CODEC_HIDDEN = (collect_submodules("pydicom.pixels.decoders") + collect_submodules("pydicom.pixels.encoders")
                + ["openjpeg", "jpeg_ls", "pylibjpeg"])
CODEC_METADATA = []
for dist in ("pylibjpeg", "pylibjpeg-openjpeg", "pyjpegls", "pydicom", "pynetdicom"):
    try:
        CODEC_METADATA += copy_metadata(dist)
    except Exception:  # pacote ausente: o build segue e o autoteste aponta o codec indisponível
        pass

# Impressão Windows (Fase 4): pywin32 é importado sob demanda pelo backend de impressão.
WIN32_HIDDEN = (["win32print", "win32ui", "win32gui", "win32con", "pywintypes", "PIL.ImageWin",
                 "win32crypt", "pythoncom", "win32com", "win32com.client"]
                if sys.platform == "win32" else [])

# Partes do Pillow que o VYONIX não usa (AVIF sozinho tem ~7,5 MB).
PIL_EXCLUDES = ["PIL._avif", "PIL.AvifImagePlugin", "PIL._webp", "PIL.WebPImagePlugin",
                "PIL.ImageQt", "PIL._imagingcms", "PIL.ImageCms", "PIL._imagingtk", "PIL.ImageTk"]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / "assets"), "assets"), (str(ROOT / "print_templates"), "print_templates")] + CODEC_METADATA,
    hiddenimports=[f"{QT_BINDING}.QtSvg"] + CODEC_HIDDEN + WIN32_HIDDEN,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "tests", "license_admin", "license_manager", "unittest.mock",
              OTHER_BINDING, "shiboken6" if QT_BINDING == "PySide2" else "shiboken2"] + PIL_EXCLUDES
             + (SLIM_EXCLUDES if SLIM else []),
    noarchive=False,
)

# Defesa adicional: nada do License Manager, de emissão de licenças ou de chaves no pacote.
for entry in list(a.datas):
    if "license_admin" in entry[0] or "license_manager" in entry[0] or entry[0].lower().endswith((".pem", ".key")):
        raise SystemExit(f"Arquivo proibido no pacote: {entry[0]}")
for name, *_ in a.pure:
    if name.split(".")[0] in ("license_manager", "license_admin"):
        raise SystemExit(f"Módulo proibido no pacote comercial: {name}")

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

# ---------------------------------------------------------------- serviço Windows (Fase 7)
# Executável separado, sem Qt: roda na sessão 0 pelo Gerenciador de Serviços.
SERVICE_HIDDEN = (["win32serviceutil", "win32service", "win32event", "servicemanager", "win32timezone"]
                  if sys.platform == "win32" else [])
s = Analysis(
    [str(ROOT / "packaging" / "service_launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / "assets" / "fonts"), "assets/fonts"), (str(ROOT / "assets" / "reception"), "assets/reception"),
           (str(ROOT / "print_templates"), "print_templates")]
          + CODEC_METADATA,
    hiddenimports=CODEC_HIDDEN + WIN32_HIDDEN + SERVICE_HIDDEN,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "tests", "license_admin", "license_manager", "unittest.mock", "PySide6", "PySide2", "shiboken6",
              "shiboken2", "app.ui"] + PIL_EXCLUDES,
    noarchive=False,
)
for entry in list(s.datas):
    if "license_admin" in entry[0] or entry[0].lower().endswith((".pem", ".key")):
        raise SystemExit(f"Arquivo proibido no pacote do serviço: {entry[0]}")
service_pyz = PYZ(s.pure)
service_exe = EXE(
    service_pyz,
    s.scripts,
    [],
    exclude_binaries=True,
    name="VyonixService",
    debug=False,
    strip=False,
    upx=False,
    console=True,
    icon=str(icon) if icon.exists() else None,
    version=str(version_file) if version_file.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    service_exe,
    s.binaries,
    s.datas,
    strip=False,
    upx=False,
    name="Vyonix",
)
