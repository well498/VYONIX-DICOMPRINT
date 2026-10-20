"""Mede o custo de gravação de eventos no SQLite com ``synchronous=FULL`` e ``NORMAL`` (WAL).

Simula o padrão atual (uma transação por evento) e o padrão em lote (N eventos por transação).

    python tools/bench_db.py <pasta> <saida.json>
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

N = 2000
BATCH = 50


def run(folder: Path, sync: str, batch: int) -> dict:
    path = folder / f"bench-{sync}-{batch}.db"
    for suffix in ("", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA synchronous={sync}")
    conn.execute("CREATE TABLE events(id INTEGER PRIMARY KEY, ts TEXT, level TEXT, category TEXT,"
                 " action TEXT, message TEXT, details_json TEXT)")
    row = ("2026-10-20T00:00:00.000Z", "INFO", "dicom", "store", "Instância recebida de CT_SALA2",
           '{"sop_class":"1.2.840.10008.5.1.4.1.1.2","bytes":524288}')
    t = time.perf_counter()
    for i in range(0, N, batch):
        conn.execute("BEGIN")
        for _ in range(batch):
            conn.execute("INSERT INTO events(ts,level,category,action,message,details_json)"
                         " VALUES (?,?,?,?,?,?)", row)
        conn.execute("COMMIT")
    dt = time.perf_counter() - t
    conn.close()
    return {"synchronous": sync, "events_per_transaction": batch, "events": N,
            "total_ms": round(dt * 1000), "ms_per_event": round(dt * 1000 / N, 3),
            "events_per_second": round(N / dt)}


def main(folder: str, out: str) -> None:
    f = Path(folder)
    shutil.rmtree(f, ignore_errors=True)
    f.mkdir(parents=True)
    results = [run(f, s, b) for s in ("FULL", "NORMAL") for b in (1, BATCH)]
    for r in results:
        print(json.dumps(r))
    Path(out).write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
