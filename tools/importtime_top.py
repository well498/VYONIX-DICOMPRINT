"""Resume a saída de ``python -X importtime``: módulos com maior tempo cumulativo (nível superior)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

LINE = re.compile(r"import time:\s+(\d+)\s+\|\s+(\d+)\s+\|(\s*)(\S+)")


def main(src: str, dst: str) -> None:
    rows = []
    for line in Path(src).read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE.match(line)
        if m:
            rows.append({"self_us": int(m[1]), "cumulative_us": int(m[2]),
                         "depth": len(m[3]) // 2, "module": m[4]})
    total = sum(r["self_us"] for r in rows)
    top_level = sorted((r for r in rows if r["depth"] <= 1), key=lambda r: -r["cumulative_us"])[:20]
    out = {"total_ms": round(total / 1000, 1),
           "top": [{"module": r["module"], "ms": round(r["cumulative_us"] / 1000, 1)} for r in top_level]}
    Path(dst).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
