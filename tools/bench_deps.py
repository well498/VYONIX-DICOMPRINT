"""Mede o custo das bibliotecas previstas para as próximas fases, em Windows real.

Para cada pacote: tamanho do wheel baixado, tamanho instalado (pasta isolada com dependências),
tempo de importação e memória adicional (RSS) após a importação, em processo Python novo.

    python tools/bench_deps.py <pasta_de_trabalho> <saida.json>
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

PACKAGES = [
    # (pacote pip, módulo a importar, fase, finalidade)
    ("numpy", "numpy", 3, "processamento numérico"),
    ("pillow", "PIL.Image", 3, "composição e exportação"),
    ("opencv-python-headless", "cv2", 3, "processamento de imagem (opcional)"),
    ("pydicom", "pydicom", 2, "leitura/escrita DICOM"),
    ("pynetdicom", "pynetdicom", 2, "rede DICOM"),
    ("pylibjpeg pylibjpeg-openjpeg pylibjpeg-rle", "pylibjpeg", 3, "JPEG 2000 / RLE"),
    ("python-gdcm", "gdcm", 3, "codecs DICOM (alternativa BSD)"),
    ("pywin32", "win32print", 4, "impressão Windows"),
    ("cryptography", "cryptography.hazmat.primitives.asymmetric.ed25519", 8, "licenças Ed25519"),
]

PROBE = r"""
import ctypes, json, sys, time
from ctypes import wintypes
class PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
def ws():
    c = PMC(); c.cb = ctypes.sizeof(c)
    ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb)
    return c.WorkingSetSize
sys.path.insert(0, sys.argv[2])
before = ws(); t = time.perf_counter()
__import__(sys.argv[1])
dt = time.perf_counter() - t
print(json.dumps({"import_ms": round(dt * 1000, 1), "rss_mb": round((ws() - before) / 1048576, 1)}))
"""


def dir_mb(path: Path) -> float:
    return round(sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1048576, 1)


def main(work: str, out: str) -> None:
    root = Path(work)
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    probe = root / "probe.py"
    probe.write_text(PROBE, encoding="utf-8")
    results = []
    for spec, module, phase, purpose in PACKAGES:
        name = spec.split()[0]
        target, wheels = root / f"t_{name}", root / f"w_{name}"
        entry = {"package": spec, "module": module, "phase": phase, "purpose": purpose}
        try:
            subprocess.run([sys.executable, "-m", "pip", "download", "--no-deps", "-q",
                            "--only-binary=:all:", "-d", str(wheels), *spec.split()], check=True)
            entry["wheel_mb"] = dir_mb(wheels)
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--only-binary=:all:",
                            "--target", str(target), *spec.split()], check=True)
            entry["installed_mb_with_deps"] = dir_mb(target)
            runs = []
            for _ in range(3):
                r = subprocess.run([sys.executable, "-I", str(probe), module, str(target)],
                                   capture_output=True, text=True, check=True)
                runs.append(json.loads(r.stdout.strip().splitlines()[-1]))
            entry["import_ms_first"] = runs[0]["import_ms"]
            entry["import_ms_warm"] = min(x["import_ms"] for x in runs[1:])
            entry["rss_mb"] = max(x["rss_mb"] for x in runs)
        except Exception as exc:  # noqa: BLE001
            entry["error"] = str(exc)[:300]
        results.append(entry)
        print(json.dumps(entry, ensure_ascii=False))
    Path(out).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
