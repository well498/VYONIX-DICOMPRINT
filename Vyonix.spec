# -*- mode: python ; coding: utf-8 -*-
# PyInstaller — VYONIX DICOM Print (distribuição onedir).
#
#   python tools/make_icon.py            # gera build/vyonix.ico e imagens do instalador
#   python tools/make_version_info.py    # gera build/version_info.txt a partir de app.__version__
#   python -m PyInstaller --noconfirm --clean Vyonix.spec
#
# Resultado: dist/Vyonix/Vyonix.exe
# A pasta license_admin/ (ferramenta de emissão e chave privada) NUNCA é incluída.

from pathlib import Path

ROOT = Path(SPECPATH).resolve()
BUILD = ROOT / "build"
icon = BUILD / "vyonix.ico"
version_file = BUILD / "version_info.txt"

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / "assets"), "assets")],
    hiddenimports=["PySide6.QtSvg"],          # renderização do logotipo/ícone SVG
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "tests", "license_admin", "unittest.mock"],
    noarchive=False,
)

# Defesa adicional: nada de license_admin ou de chaves no pacote.
for entry in list(a.datas):
    if "license_admin" in entry[0] or entry[0].lower().endswith((".pem", ".key")):
        raise SystemExit(f"Arquivo proibido no pacote: {entry[0]}")

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
