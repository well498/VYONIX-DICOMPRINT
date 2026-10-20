"""Verifica se todas as DLLs importadas pelos binários empacotados estão disponíveis.

Para cada .exe/.dll/.pyd da pasta onedir, lê a tabela de importação (PE) e procura cada DLL
importada: na própria pasta do pacote, na pasta de sistema do Windows ou como conjunto de API
(``api-ms-win-*``/``ext-ms-*``). Falha (código 1) e lista o que estiver faltando — protege a
distribuição enxuta contra a remoção de uma DLL necessária.

    python tools/check_dll_deps.py dist\\Vyonix
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pefile


def main(folder: str) -> int:
    root = Path(folder)
    bundled = {p.name.lower(): p for p in root.rglob("*") if p.suffix.lower() in (".dll", ".pyd", ".exe")}
    system_dirs = [Path(os.environ.get("SystemRoot", r"C:\Windows")) / d for d in ("System32", "SysWOW64")]
    missing: dict[str, set[str]] = {}
    checked = 0
    for name, path in sorted(bundled.items()):
        try:
            pe = pefile.PE(str(path), fast_load=True)
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                                                   pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
        except pefile.PEFormatError:
            continue
        checked += 1
        entries = list(getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])) + list(getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", []))
        for entry in entries:
            dep = entry.dll.decode("ascii", "replace").lower()
            if dep in bundled or dep.startswith(("api-ms-win-", "ext-ms-")):
                continue
            if any((d / dep).exists() for d in system_dirs):
                continue
            missing.setdefault(dep, set()).add(str(path.relative_to(root)))
    print(f"{checked} binários verificados, {len(bundled)} no pacote.")
    if missing:
        for dep, users in sorted(missing.items()):
            print(f"FALTANDO: {dep}  <- {', '.join(sorted(users)[:6])}")
            print(f"::error title=DLL ausente no pacote::{dep} é importada por {', '.join(sorted(users)[:6])}")
        return 1
    print("Nenhuma dependência ausente.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
