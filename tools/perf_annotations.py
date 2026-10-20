"""Publica os resultados da análise de desempenho como anotações do GitHub Actions.

As anotações ficam legíveis pela API de *check runs*, o que permite consultar os números
sem baixar artefatos. Cada anotação carrega um bloco JSON compacto.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

LIMIT = 6000


def emit(level: str, title: str, text: str) -> None:
    text = text.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    print(f"::{level} title={title}::{text}")


def load(path: Path):
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    return json.loads(raw) if path.suffix == ".json" else raw


def main(folder: str) -> None:
    d = Path(folder)
    payload = {}
    for name in ("padrao", "enxuta"):
        r = load(d / f"{name}.json")
        if r:
            r = dict(r)
            disk = dict(r.get("disk", {}))
            disk["top_files"] = disk.get("top_files", [])[:15]
            r["disk"] = disk
            payload[name] = r
    payload["importtime"] = load(d / "importtime.json")
    payload["deps"] = load(d / "deps.json")
    payload["db"] = load(d / "db.json")
    removed = load(d / "slim_removed.txt") or ""
    rows = [ln.split("\t") for ln in removed.splitlines() if "\t" in ln]
    payload["slim_removed"] = {"count": len(rows),
                               "mb": round(sum(int(s) for s, _ in rows) / 1048576, 2),
                               "largest": [[f, round(int(s) / 1048576, 2)] for s, f in rows[:25]]}
    val = load(d / "validate-slim" / "results.json")
    if val:
        payload["validate_slim"] = [[x["id"], x["ok"], x["detail"][:140]] for x in val["results"]]

    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    chunks = [blob[i:i + LIMIT] for i in range(0, len(blob), LIMIT)]
    for i, chunk in enumerate(chunks[:9], 1):
        emit("notice", f"perf {i}/{len(chunks)}", chunk)
    tail = load(d / "pytest.txt")
    if tail and ("failed" in tail or "error" in tail.lower()):
        emit("warning", "pytest", "\n".join(tail.splitlines()[-40:]))


if __name__ == "__main__":
    main(sys.argv[1])
