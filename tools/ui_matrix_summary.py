"""Resumo da matriz de interface (tests/test_ui_matrix.py) como anotações do GitHub Actions."""

import json
import sys
from pathlib import Path


def esc(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


def main(folder: str) -> int:
    files = sorted(Path(folder).glob("*.json"))
    if not files:
        print(f"::warning::Nenhum resultado da matriz de interface em {folder}")
        return 0
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        name = d.get("config", {}).get("name", f.stem)
        if "crash" in d:
            print(f"::error title=Matriz {name}::{esc(d['crash'][-3000:])}")
            continue
        telas = "; ".join(f"{s['name']} {s['geometry'][2]}×{s['geometry'][3]} lógicos, escala {s['dpr']}"
                          for s in d["screens"])
        contr = ", ".join(f"{k} {v['ratio']}:1" for k, v in sorted(d["contrast"].items()))
        issues = d["issues"]
        line = (f"{telas} | janela na tela {d['screen_index'] + 1} | {d['pages']} páginas, "
                f"{d['dialogs']} diálogos | contraste medido: {contr} | problemas: {len(issues)} | {d.get('seconds', '?')} s")
        print(f"::notice title=Matriz {name}::{esc(line)}")
        if issues:
            print(f"::error title=Matriz {name} ({len(issues)} problemas)::{esc(chr(10).join(issues[:60]))}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
