"""SBOM (CycloneDX) e análise de vulnerabilidades conhecidas (pip-audit/OSV) de um ambiente Python.

Prompt Mestre §50 (inventário de componentes, SBOM, análise de vulnerabilidades). Roda no CI com as
ferramentas instaladas num ambiente separado, para que elas não entrem no inventário do produto:

    python -m venv %RUNNER_TEMP%\\sbomtools
    %RUNNER_TEMP%\\sbomtools\\Scripts\\python -m pip install "cyclonedx-bom>=4,<8" "pip-audit>=2.7,<3"
    %RUNNER_TEMP%\\sbomtools\\Scripts\\python tools\\sbom_audit.py <python_do_produto> <pasta_saida> <nome>

Gera ``<nome>.cdx.json`` (SBOM), ``<nome>.freeze.txt`` e ``<nome>.audit.json``; publica um resumo e cada
vulnerabilidade como anotação. Vulnerabilidades não interrompem o build: entram na triagem (o resultado
fica registrado e o pacote é atualizado na próxima entrega, ou a exceção é justificada).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def esc(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


def main(product_python: str, out_dir: str, name: str) -> int:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tools_bin = Path(sys.executable).parent
    freeze = subprocess.run([product_python, "-m", "pip", "freeze", "--all", "--exclude-editable"],
                            capture_output=True, text=True, check=True).stdout
    pinned = [ln for ln in freeze.splitlines() if "==" in ln and not ln.startswith(("pip==", "setuptools==", "wheel=="))]
    (out / f"{name}.freeze.txt").write_text("\n".join(pinned) + "\n", encoding="utf-8")

    sbom = out / f"{name}.cdx.json"
    r = subprocess.run([str(tools_bin / "cyclonedx-py"), "environment", "--of", "JSON", "-o", str(sbom), product_python],
                       capture_output=True, text=True)
    if r.returncode != 0 or not sbom.exists():
        print(f"::error title=SBOM {name}::{esc((r.stdout + r.stderr)[-3000:])}")
        return 1
    components = len(json.loads(sbom.read_text(encoding="utf-8")).get("components", []))

    audit = out / f"{name}.audit.json"
    r = subprocess.run([str(tools_bin / "pip-audit"), "-r", str(out / f"{name}.freeze.txt"), "--no-deps",
                        "--disable-pip", "--format", "json", "-o", str(audit), "--progress-spinner", "off"],
                       capture_output=True, text=True)
    if not audit.exists():
        print(f"::error title=pip-audit {name}::{esc((r.stdout + r.stderr)[-3000:])}")
        return 1
    data = json.loads(audit.read_text(encoding="utf-8"))
    deps = data.get("dependencies", data if isinstance(data, list) else [])
    vulns = [(d["name"], d["version"], v) for d in deps for v in d.get("vulns", [])]
    skipped = [d["name"] for d in deps if d.get("skip_reason")]
    print(f"::notice title=SBOM {name}::{components} componentes no SBOM CycloneDX; {len(pinned)} pacotes "
          f"auditados; {len(vulns)} vulnerabilidade(s) conhecida(s)"
          + (f"; não auditados: {', '.join(skipped)}" if skipped else ""))
    dependents = _dependents(product_python, sorted({p for p, _v, _x in vulns}))
    for pkg, ver, v in vulns[:40]:
        fix = ", ".join(v.get("fix_versions") or []) or "sem correção publicada"
        who = ", ".join(dependents.get(pkg.lower(), [])) or "nenhum pacote do ambiente (instalado diretamente ou pela imagem)"
        print(f"::warning title=Vulnerabilidade {pkg} {ver}::{esc(v.get('id', '?') + ' - corrigida em: ' + fix + ' - exigido por: ' + who)}")
    (out / f"{name}.vulnerable.json").write_text(json.dumps(
        {"packages": sorted({p for p, _v, _x in vulns}), "dependents": dependents}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return 0


_DEPENDENTS = r"""
import json, re, sys
from importlib import metadata
want = {w.lower().replace("_", "-") for w in sys.argv[1:]}
out = {w: [] for w in want}
for d in metadata.distributions():
    for req in d.requires or []:
        n = re.split(r"[ ;<>=!~\[(]", req, 1)[0].lower().replace("_", "-")
        if n in want and "extra ==" not in req:
            out[n].append(f"{d.metadata['Name']} {d.version}")
print(json.dumps(out))
"""


def _dependents(product_python: str, packages: list[str]) -> dict[str, list[str]]:
    """Quem, no ambiente do produto, exige cada pacote vulnerável (para saber de onde ele vem)."""
    if not packages:
        return {}
    r = subprocess.run([product_python, "-c", _DEPENDENTS, *packages], capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except ValueError:
        return {}


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
