"""Passo 4 do incidente INC-2026-10-23: aplica em ``app/licensing/keys.py`` a chave pública nova e a
restrição da chave comprometida, a partir dos dois arquivos exportados pelo License Manager do fornecedor.

Uso:
    python tools/apply_key_rotation.py --public VYONIX_chave_publica_vyx-2026-02.txt \\
        --restriction VYONIX_restricao_vyx-2026-01_<data>.json [--keys-file app/licensing/keys.py] [--dry-run]

Entradas (nenhuma é segredo):
* ``--public``: a linha exportada por "Exportar chave pública…" (``"<key_id>": "<64 hex>"``).
* ``--restriction``: o JSON ``vyonix-keyrestriction/1`` de "Exportar documentos legítimos…".

Recusas: qualquer arquivo com bloco de chave privada; chave pública que não seja Ed25519 de 32 bytes;
identificador fora do padrão ou já existente; restrição de chave desconhecida, da própria chave nova,
lista vazia ou hash inválido. O resultado é reimportado e conferido antes de ser gravado.
Não mexe em licenças nem gera chaves — a chave privada nova nunca passa pelo desenvolvimento.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY_ID = re.compile(r"^vyx-(srv-)?\d{4}-\d{2}$")
PUBLIC_LINE = re.compile(r'"(?P<id>[a-z0-9-]+)"\s*:\s*"(?P<hex>[0-9a-fA-F]+)"')
HEX64 = re.compile(r"^[0-9a-f]{64}$")
PRIVATE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|private_pem|\"d\"\s*:")
LICENSE_SCOPES = ("license", "authorization", "revalidation", "revocation")


class RotationError(ValueError):
    pass


def _read(path: Path) -> str:
    text = Path(path).read_text(encoding="utf-8")
    if PRIVATE.search(text):
        raise RotationError(f"{Path(path).name} parece conter material de chave privada. Nada foi alterado; "
                            "descarte esse arquivo com segurança e exporte só a chave pública.")
    return text


def parse_public(path: Path) -> tuple[str, str]:
    m = PUBLIC_LINE.search(_read(path))
    if not m:
        raise RotationError("Arquivo da chave pública sem a linha \"<key_id>\": \"<hex>\".")
    key_id, hexkey = m.group("id"), m.group("hex").lower()
    if not KEY_ID.match(key_id):
        raise RotationError(f"Identificador de chave fora do padrão: {key_id}")
    if not HEX64.match(hexkey):
        raise RotationError("A chave pública deve ter 32 bytes (64 caracteres hexadecimais).")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(hexkey))
    except ValueError as exc:
        raise RotationError("Não é uma chave pública Ed25519 válida.") from exc
    return key_id, hexkey


def parse_restriction(path: Path) -> tuple[str, list[str], dict]:
    try:
        m = json.loads(_read(path))
    except json.JSONDecodeError as exc:
        raise RotationError("Arquivo de restrição não é JSON válido.") from exc
    if m.get("format") != "vyonix-keyrestriction/1":
        raise RotationError("Formato de restrição desconhecido (esperado vyonix-keyrestriction/1).")
    key_id = m.get("key_id", "")
    if not KEY_ID.match(key_id):
        raise RotationError(f"Identificador de chave fora do padrão: {key_id}")
    hashes = sorted({str(d.get("sha256", "")).lower() for d in m.get("documents", [])})
    if not hashes:
        raise RotationError("A lista de documentos legítimos está vazia: aplicar a restrição invalidaria todas as "
                            "licenças da chave. Confira a exportação no License Manager.")
    bad = [h for h in hashes if not HEX64.match(h)]
    if bad:
        raise RotationError(f"{len(bad)} hash(es) inválido(s) na lista de documentos.")
    if int(m.get("count", len(hashes))) != len(m.get("documents", [])):
        raise RotationError("A contagem declarada não confere com a lista de documentos.")
    return key_id, hashes, m


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("_keys_check", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _insert_before_close(src: str, header: str, block: str) -> str:
    start = src.index(header)
    close = src.index("\n}", start)
    return src[:close] + "\n" + block.rstrip("\n") + src[close:]


def apply(keys_file: Path, public: tuple[str, str], restriction: tuple[str, list[str], dict]) -> str:
    new_id, new_hex = public
    old_id, hashes, manifest = restriction
    cur = _load(keys_file)
    if new_id in cur.PUBLIC_KEYS:
        raise RotationError(f"A chave {new_id} já está em PUBLIC_KEYS.")
    if new_hex in cur.PUBLIC_KEYS.values():
        raise RotationError("Esta chave pública já consta com outro identificador.")
    if old_id not in cur.PUBLIC_KEYS:
        raise RotationError(f"A chave a restringir ({old_id}) não está em PUBLIC_KEYS.")
    if old_id == new_id:
        raise RotationError("A restrição não pode ser da chave nova.")
    if old_id in cur.RESTRICTED_KEYS:
        raise RotationError(f"A chave {old_id} já está restrita.")
    scopes = cur.KEY_SCOPES.get(old_id, LICENSE_SCOPES)

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey  # noqa: F401
    import hashlib
    fp = hashlib.sha256(bytes.fromhex(new_hex)).hexdigest().upper()
    fp = ":".join(fp[i:i + 4] for i in range(0, 24, 4))

    src = keys_file.read_text(encoding="utf-8")
    src = _insert_before_close(src, "PUBLIC_KEYS: dict[str, str] = {",
                               f"    # {new_id} — VYONIX License Manager — impressão digital {fp}\n"
                               f'    "{new_id}": "{new_hex}",')
    src = _insert_before_close(src, "KEY_SCOPES: dict[str, tuple[str, ...]] = {",
                               f'    "{new_id}": {tuple(scopes)!r},')
    restr = (f"    # {old_id}: comprometida (INC-2026-10-23); {len(hashes)} documento(s) legítimo(s) exportado(s) em "
             f"{manifest.get('generated_at', '?')}\n    \"{old_id}\": frozenset({{\n"
             + "".join(f'        "{h}",\n' for h in hashes) + "    }),")
    if "RESTRICTED_KEYS: dict[str, frozenset[str]] = {}" in src:
        src = src.replace("RESTRICTED_KEYS: dict[str, frozenset[str]] = {}",
                          "RESTRICTED_KEYS: dict[str, frozenset[str]] = {\n" + restr + "\n}", 1)
    else:
        src = _insert_before_close(src, "RESTRICTED_KEYS: dict[str, frozenset[str]] = {", restr)
    return src


def verify(src: str, tmp_dir: Path, public, restriction) -> None:
    probe = tmp_dir / "_keys_probe.py"
    probe.write_text(src, encoding="utf-8")
    try:
        mod = _load(probe)
    finally:
        probe.unlink(missing_ok=True)
    new_id, new_hex = public
    old_id, hashes, _ = restriction
    assert mod.PUBLIC_KEYS[new_id] == new_hex
    assert set(mod.KEY_SCOPES[new_id]) == set(mod.KEY_SCOPES[old_id])
    assert mod.RESTRICTED_KEYS[old_id] == frozenset(hashes)
    assert new_id not in mod.RESTRICTED_KEYS
    assert mod.key_policy_error(old_id, b"documento-forjado") is not None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--public", required=True, type=Path)
    ap.add_argument("--restriction", required=True, type=Path)
    ap.add_argument("--keys-file", type=Path, default=ROOT / "app" / "licensing" / "keys.py")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    try:
        public, restriction = parse_public(a.public), parse_restriction(a.restriction)
        src = apply(a.keys_file, public, restriction)
        verify(src, a.keys_file.parent, public, restriction)
    except RotationError as exc:
        print(f"RECUSADO: {exc}", file=sys.stderr)
        return 2
    print(f"Chave nova: {public[0]}; restrição: {restriction[0]} com {len(restriction[1])} documento(s) legítimo(s).")
    if a.dry_run:
        print("Simulação (--dry-run): keys.py não foi alterado.")
        return 0
    a.keys_file.write_text(src, encoding="utf-8")
    print(f"Gravado: {a.keys_file}. Próximo: testes, build e release candidata (publicação exige aprovação).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
