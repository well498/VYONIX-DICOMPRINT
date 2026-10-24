"""Confere se algum pacote com vulnerabilidade conhecida (saída do ``tools/sbom_audit.py``) foi parar no pacote
distribuído (pasta do PyInstaller). Publica o resultado como anotação; falha se um deles estiver no pacote.

Uso: ``python tools/bundle_vuln_check.py dist/sbom/<nome>.vulnerable.json <pasta_do_pacote> [...]``
"""

import json
import sys
from pathlib import Path


def main(vuln_file: str, *bundles: str) -> int:
    path = Path(vuln_file)
    pkgs = json.loads(path.read_text(encoding="utf-8")).get("packages", []) if path.exists() else []
    if not pkgs:
        print("::notice title=Pacote distribuído::nenhuma dependência com vulnerabilidade conhecida a conferir")
        return 0
    found: dict[str, list[str]] = {}
    for b in bundles:
        for p in Path(b).rglob("*"):
            n = p.name.lower().replace("-", "_")
            for pkg in pkgs:
                k = pkg.lower().replace("-", "_")
                if n == k or n.startswith(k + "-") or n.startswith(k + "."):
                    found.setdefault(pkg, []).append(str(p))
    for pkg in pkgs:
        if pkg in found:
            print(f"::error title=Vulnerável no pacote::{pkg} está no pacote distribuído: {found[pkg][:3]}")
        else:
            print(f"::notice title=Pacote distribuído::{pkg} (com vulnerabilidade conhecida) NÃO está no pacote "
                  f"distribuído ({', '.join(bundles)}): afeta só o ambiente de build")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
