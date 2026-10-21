"""Gera ``build/version_info.txt`` (recurso VERSIONINFO do Vyonix.exe) e imprime as versões.

``app.__version__`` (ex.: ``1.0.0.dev1``) é a fonte única. A versão numérica do Windows
(quatro inteiros) é derivada dela: ``1.0.0.dev1`` → ``1.0.0.1``; ``1.0.0`` → ``1.0.0.0``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import __version__, brand  # noqa: E402


def numeric_version(version: str) -> tuple[int, int, int, int]:
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:\.?(?:dev|rc|b|a)(\d+))?", version)
    if not m:
        raise SystemExit(f"Versão não reconhecida: {version}")
    return int(m[1]), int(m[2]), int(m[3]), int(m[4] or 0)


TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(filevers={nv}, prodvers={nv}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041604B0', [
      StringStruct('CompanyName', '{brand}'),
      StringStruct('FileDescription', '{product}'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', '{internal}'),
      StringStruct('LegalCopyright', '{brand}'),
      StringStruct('OriginalFilename', '{original}'),
      StringStruct('ProductName', '{product}'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1046, 1200])])
  ]
)
"""


def main() -> None:
    nv = numeric_version(__version__)
    out = ROOT / "build" / "version_info.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(TEMPLATE.format(nv=nv, brand=brand.BRAND, product=brand.PRODUCT_NAME,
                                   version=__version__, internal="Vyonix", original="Vyonix.exe"), encoding="utf-8")
    from license_manager import APP_NAME, __version__ as lm_version
    lnv = numeric_version(lm_version)
    (ROOT / "build" / "version_info_lm.txt").write_text(
        TEMPLATE.format(nv=lnv, brand=brand.BRAND, product=APP_NAME, version=lm_version,
                        internal="VYONIX_License_Manager", original="VYONIX_License_Manager.exe"), encoding="utf-8")
    from license_server import APP_NAME as LS_NAME, __version__ as ls_version
    (ROOT / "build" / "version_info_ls.txt").write_text(
        TEMPLATE.format(nv=numeric_version(ls_version), brand=brand.BRAND, product=LS_NAME, version=ls_version,
                        internal="VYONIX_License_Server", original="VYONIX_License_Server.exe"), encoding="utf-8")
    print(f"APP_VERSION={__version__}")
    print("FILE_VERSION=" + ".".join(map(str, nv)))
    print(f"LM_VERSION={lm_version}")
    print("LM_FILE_VERSION=" + ".".join(map(str, lnv)))


if __name__ == "__main__":
    main()
