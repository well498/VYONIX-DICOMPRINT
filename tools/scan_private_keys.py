"""Procura blocos PEM de chave privada (com conteúdo) em arquivos e pastas; código 1 se encontrar.

Uso: python tools/scan_private_keys.py <arquivo-ou-pasta> [...]
Os executáveis compactados (instaladores, onefile) são verificados também por dentro no autoteste
do próprio programa (``--self-test`` do License Manager varre a pasta extraída).
"""

import re
import sys
from pathlib import Path

PEM = re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----\r?\n[A-Za-z0-9+/=\r\n]{40,}")
ANY_PRIVATE = re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")
CERT = re.compile(rb"-----BEGIN CERTIFICATE-----")


def files(paths):
    for p in map(Path, paths):
        if p.is_dir():
            yield from (f for f in p.rglob("*") if f.is_file())
        elif p.is_file():
            yield p


def main(argv):
    hits, n = [], 0
    for f in files(argv):
        n += 1
        if is_private(f):
            hits.append(str(f))
    print(f"{n} arquivo(s) verificados; {len(hits)} com chave privada" + (": " + ", ".join(hits) if hits else ""))
    for h in hits:
        print(f"::error title=Chave privada no pacote::{h}")
    return 1 if hits else 0


def is_private(f: Path) -> bool:
    """Bloco PEM de chave privada em qualquer arquivo; ``.key`` sempre; ``.pem`` com qualquer cabeçalho de
    chave privada ou que não seja só certificados (um ``cacert.pem`` de autoridades certificadoras é público)."""
    data = f.read_bytes()
    if PEM.search(data):
        return True
    suf = f.suffix.lower()
    if suf == ".key":
        return True
    if suf == ".pem":
        return bool(ANY_PRIVATE.search(data)) or not CERT.search(data)
    return False


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
