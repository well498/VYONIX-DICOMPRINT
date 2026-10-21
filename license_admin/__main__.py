"""Emissão de licenças offline do VYONIX DICOM Print (uso exclusivo do fornecedor).

Requer ``pip install -r license_admin/requirements.txt`` (biblioteca ``cryptography``).

    python -m license_admin keygen --key-id prod-1 --out D:\\cofre\\vyonix
    python -m license_admin request "VYXR1-..."                       # mostra o conteúdo do pedido
    python -m license_admin issue --key D:\\cofre\\vyonix\\vyonix-prod-1.private.pem --key-id prod-1 \\
        --request "VYXR1-..." --licensee "Clínica Exemplo Ltda" --document 00.000.000/0001-00 \\
        --edition profissional --days 365 --out licenca.vylic
    python -m license_admin verify licenca.vylic

A chave privada fica só com o fornecedor (de preferência cifrada com --passphrase). Cada emissão é
registrada em ``emitidas.csv`` na pasta da chave.
"""

from __future__ import annotations

import argparse
import csv
import getpass
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from app.licensing.license import (ALL_FEATURES, FORMAT, PRODUCT, b64e, canonical, new_license_id, parse_license,
                                   parse_request, verify_signature)

EDITIONS: dict[str, dict] = {
    "essencial": {"label": "Essencial", "features": ["storage", "printing"], "max_devices": 2},
    "profissional": {"label": "Profissional", "features": ["storage", "printing", "print_scp", "rules"],
                     "max_devices": 10},
    "corporativo": {"label": "Corporativo", "features": list(ALL_FEATURES), "max_devices": None},
}


def _crypto():
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        sys.exit("Instale a dependência: pip install -r license_admin/requirements.txt")
    return serialization, Ed25519PrivateKey


def keygen(args) -> int:
    serialization, Ed25519PrivateKey = _crypto()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"vyonix-{args.key_id}.private.pem"
    if path.exists():
        sys.exit(f"{path} já existe — não sobrescrevo chaves.")
    passphrase = getpass.getpass("Senha para cifrar a chave (vazio = sem senha): ") if args.passphrase else ""
    enc = (serialization.BestAvailableEncryption(passphrase.encode()) if passphrase
           else serialization.NoEncryption())
    key = Ed25519PrivateKey.generate()
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, enc))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    print(f"Chave privada: {path}  (guarde em local seguro; NUNCA coloque no repositório ou no instalador)")
    print("Acrescente ao app/licensing/keys.py e recompile o VYONIX:")
    print(f'    "{args.key_id}": "{pub}",')
    return 0


def _load_key(path: str, ask: bool):
    serialization, _ = _crypto()
    data = Path(path).read_bytes()
    password = getpass.getpass("Senha da chave: ").encode() if ask else None
    return serialization.load_pem_private_key(data, password=password)


def show_request(args) -> int:
    print(json.dumps(parse_request(args.code), ensure_ascii=False, indent=2))
    return 0


def issue(args) -> int:
    text = args.request
    if not text.strip().startswith("VYXR1-"):        # caminho de um arquivo com o código
        text = Path(text).read_text(encoding="utf-8")
    req = parse_request(text)
    if req.get("product") != PRODUCT:
        sys.exit(f"Pedido de outro produto: {req.get('product')}")
    ed = EDITIONS[args.edition]
    features = sorted(set(args.feature or ed["features"]))
    unknown = set(features) - set(ALL_FEATURES)
    if unknown:
        sys.exit(f"Recursos desconhecidos: {', '.join(sorted(unknown))}")
    expires = (date.today() + timedelta(days=args.days)).isoformat() if args.days else None
    payload = {
        "v": 1, "license_id": new_license_id(), "product": PRODUCT, "edition": ed["label"],
        "licensee": args.licensee, "document": args.document, "installation_id": req["installation_id"],
        "machine_id": req["machine_id"], "features": features,
        "max_devices": args.max_devices if args.max_devices is not None else ed["max_devices"],
        "issued_at": date.today().isoformat(), "expires_at": expires, "notes": args.notes,
    }
    signed = canonical(payload)
    key = _load_key(args.key, args.ask_passphrase)
    signature = key.sign(signed)
    doc = {"format": FORMAT, "v": 1, "key_id": args.key_id, "payload": b64e(signed), "signature": b64e(signature)}
    text = json.dumps(doc, indent=2)
    _, s, sig, kid = parse_license(text)
    if not verify_signature(s, sig, kid):
        sys.exit("A assinatura não confere com a chave pública embutida no VYONIX para "
                 f"'{args.key_id}'. Verifique --key/--key-id e app/licensing/keys.py.")
    Path(args.out).write_text(text, encoding="utf-8")
    log = Path(args.key).parent / "emitidas.csv"
    new = not log.exists()
    with log.open("a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["license_id", "emitida", "validade", "licenciado", "documento", "edicao", "instalacao",
                        "computador", "recursos", "arquivo"])
        w.writerow([payload["license_id"], payload["issued_at"], expires or "sem vencimento", args.licensee,
                    args.document or "", ed["label"], req["installation_id"], req["machine_id"],
                    " ".join(features), args.out])
    print(f"Licença {payload['license_id']} gravada em {args.out} ({ed['label']}, "
          f"{'até ' + expires if expires else 'sem vencimento'}).")
    return 0


def verify(args) -> int:
    payload, signed, signature, key_id = parse_license(Path(args.file).read_text(encoding="utf-8"))
    ok = verify_signature(signed, signature, key_id)
    print(json.dumps({"assinatura_valida": ok, "key_id": key_id, **payload}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="license_admin", description="Emissão de licenças do VYONIX DICOM Print")
    sub = p.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen", help="gera um novo par de chaves Ed25519")
    k.add_argument("--key-id", required=True)
    k.add_argument("--out", required=True, help="pasta segura (fora do repositório)")
    k.add_argument("--passphrase", action="store_true", help="cifra a chave privada com senha")
    r = sub.add_parser("request", help="mostra o conteúdo de um código de solicitação")
    r.add_argument("code")
    i = sub.add_parser("issue", help="emite e assina uma licença")
    i.add_argument("--key", required=True)
    i.add_argument("--key-id", required=True)
    i.add_argument("--ask-passphrase", action="store_true")
    i.add_argument("--request", required=True, help="código VYXR1-... ou arquivo com o código")
    i.add_argument("--licensee", required=True)
    i.add_argument("--document")
    i.add_argument("--edition", choices=sorted(EDITIONS), default="profissional")
    i.add_argument("--feature", action="append", help="sobrepõe os recursos da edição (repetível)")
    i.add_argument("--max-devices", type=int)
    i.add_argument("--days", type=int, default=365, help="validade em dias (0 = sem vencimento)")
    i.add_argument("--notes")
    i.add_argument("--out", required=True)
    v = sub.add_parser("verify", help="confere a assinatura de um arquivo .vylic")
    v.add_argument("file")
    args = p.parse_args(argv)
    return {"keygen": keygen, "request": show_request, "issue": issue, "verify": verify}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
