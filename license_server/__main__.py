"""Linha de comando do VYONIX License Server.

    VYONIX_License_Server.exe init --data PASTA --admin USUARIO --hostname licencas.exemplo.com.br
                                   --key-file vyx-srv-2026-01.private.pem --key-id vyx-srv-2026-01
    VYONIX_License_Server.exe serve --data PASTA
    VYONIX_License_Server.exe user-add --data PASTA --username fin1 --role financial
    VYONIX_License_Server.exe register --data PASTA --license cliente.vylic --plan monthly --price 49900
    VYONIX_License_Server.exe evaluate --data PASTA
    VYONIX_License_Server.exe pin --data PASTA
    VYONIX_License_Server.exe selftest

Frase-senha da chave de assinatura: variável ``VYONIX_LS_KEY_PASSPHRASE`` ou o arquivo indicado em
``signing_passphrase_file`` (proteja-o com permissões restritas). Senhas de usuários: digitadas ou
``--password-file``.
"""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import secrets
import shutil
import sys
from pathlib import Path

from license_server import APP_NAME, DEFAULT_PORT, __version__

CONFIG = "server.json"


def _emit(obj) -> None:
    text = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    try:
        sys.stdout.write(text + "\n")
    except UnicodeEncodeError:
        sys.stdout.buffer.write((text + "\n").encode("utf-8"))


def load_config(data: Path) -> dict:
    f = data / CONFIG
    if not f.exists():
        raise SystemExit(f"Configuração não encontrada: {f}. Execute 'init' primeiro.")
    return json.loads(f.read_text(encoding="utf-8"))


def _password(args, prompt: str) -> str:
    if getattr(args, "password_file", None):
        return Path(args.password_file).read_text(encoding="utf-8").strip()
    a = getpass.getpass(prompt)
    if a != getpass.getpass("Repita: "):
        raise SystemExit("As senhas não conferem.")
    return a


def _passphrase(cfg: dict, data: Path) -> str:
    env = os.environ.get("VYONIX_LS_KEY_PASSPHRASE")
    if env:
        return env
    pf = cfg.get("signing_passphrase_file")
    if pf:
        p = Path(pf) if Path(pf).is_absolute() else data / pf
        return p.read_text(encoding="utf-8").strip()
    if sys.stdin.isatty():
        return getpass.getpass(f"Frase-senha da chave {cfg['signing_key_id']}: ")
    raise SystemExit("Informe a frase-senha da chave (VYONIX_LS_KEY_PASSPHRASE ou signing_passphrase_file).")


def build_core(data: Path, cfg: dict, *, with_signer: bool = True):
    from app.licensing.keys import KEY_SCOPES, PUBLIC_KEYS, RESTRICTED_KEYS
    from license_server.core import ServerCore, load_signer
    signer = None
    if with_signer:
        kf = Path(cfg["signing_key_file"])
        kf = kf if kf.is_absolute() else data / kf
        signer = load_signer(kf, _passphrase(cfg, data), cfg["signing_key_id"])
        from vyonix_protocol.crypto import public_hex
        pub = public_hex(signer[1])
        trusted = PUBLIC_KEYS.get(cfg["signing_key_id"])
        if trusted and trusted != pub:
            raise SystemExit("A chave carregada não corresponde à chave pública oficial "
                             f"{cfg['signing_key_id']} embutida no VYONIX DICOM Print.")
        if not trusted:
            logging.warning("A chave %s não está na lista do VYONIX DICOM Print: as instalações recusarão as "
                            "autorizações deste servidor.", cfg["signing_key_id"])
    provider = None
    inter = cfg.get("inter")
    if inter:
        from vyonix_commercial.billing.inter import InterConfig, InterProvider
        secret = Path(inter["client_secret_file"])
        secret = secret if secret.is_absolute() else data / secret
        provider = InterProvider(InterConfig(
            client_id=inter["client_id"], client_secret=secret.read_text(encoding="utf-8").strip(),
            cert_file=str(data / inter["cert_file"]) if not Path(inter["cert_file"]).is_absolute() else inter["cert_file"],
            key_file=str(data / inter["key_file"]) if not Path(inter["key_file"]).is_absolute() else inter["key_file"],
            base_url=inter.get("base_url") or "https://cdpj.partners.bancointer.com.br",
            account=inter.get("account"), ca_file=inter.get("ca_file")))
    return ServerCore(data, signer=signer, license_keys=dict(PUBLIC_KEYS), license_key_scopes=dict(KEY_SCOPES),
                      restricted_keys=dict(RESTRICTED_KEYS),
                      provider=provider, webhook_secret=cfg.get("webhook_secret", ""),
                      session_minutes=int(cfg.get("session_minutes", 30)))


def cmd_init(args) -> int:
    data = Path(args.data)
    data.mkdir(parents=True, exist_ok=True)
    if (data / CONFIG).exists():
        raise SystemExit("Esta pasta já tem um License Server configurado.")
    (data / "keys").mkdir(exist_ok=True)
    key_dst = data / "keys" / Path(args.key_file).name
    shutil.copyfile(args.key_file, key_dst)
    cfg = {"bind": args.bind, "port": args.port, "hostnames": args.hostname, "public_url":
           f"https://{args.hostname[0]}:{args.port}", "signing_key_id": args.key_id,
           "signing_key_file": str(key_dst.relative_to(data)), "signing_passphrase_file": None,
           "tls_cert": "tls/cert.pem", "tls_key": "tls/key.pem",
           "admin_networks": ["127.0.0.0/8", "::1/128", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"],
           "webhook_secret": secrets.token_urlsafe(32), "session_minutes": 30, "inter": None}
    core = build_core(data, cfg)                         # confere a chave e a frase-senha
    from license_server.http import certificate_pin, ensure_certificate
    cert, _key = ensure_certificate(data / "tls", args.hostname)
    core.create_user(None, args.admin, args.admin, "admin", _password(args, f"Senha do administrador {args.admin}: "))
    (data / CONFIG).write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    core.close()
    _emit({"ok": True, "data": str(data), "url": cfg["public_url"], "certificate_pin": certificate_pin(cert),
           "next": "Informe o endereço e a impressão digital no License Manager (Gestão Comercial → Políticas) "
                   "para as licenças online; depois execute 'serve'."})
    return 0


def cmd_serve(args) -> int:
    from license_server.http import LicenseHTTPServer, Scheduler, certificate_pin, ensure_certificate
    data = Path(args.data)
    cfg = load_config(data)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(data / "license_server.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])
    core = build_core(data, cfg)
    cert, key = data / cfg.get("tls_cert", "tls/cert.pem"), data / cfg.get("tls_key", "tls/key.pem")
    if not (cert.is_file() and key.is_file()):
        cert, key = ensure_certificate(data / "tls", cfg.get("hostnames") or ["localhost"])
    srv = LicenseHTTPServer((cfg.get("bind", "0.0.0.0"), int(args.port or cfg.get("port", DEFAULT_PORT))), core,
                            cert=cert, key=key, admin_networks=cfg.get("admin_networks") or ())
    sched = Scheduler(core)
    sched.start()
    logging.info("%s %s em https://%s:%s (certificado %s)", APP_NAME, __version__, cfg.get("bind"),
                 srv.server_address[1], certificate_pin(cert))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        sched.stop.set()
        srv.server_close()
        core.close()
    return 0


def cmd_user_add(args) -> int:
    data = Path(args.data)
    core = build_core(data, load_config(data), with_signer=False)
    from license_server.core import SessionUser
    r = core.db.conn().execute("SELECT * FROM users WHERE role = 'admin' AND active = 1 ORDER BY id LIMIT 1").fetchone()
    by = SessionUser(r["id"], r["username"], r["display_name"], "admin")
    core.create_user(by, args.username, args.display_name or args.username, args.role,
                     _password(args, f"Senha de {args.username}: "))
    _emit({"ok": True, "user": args.username, "role": args.role})
    return 0


def cmd_register(args) -> int:
    data = Path(args.data)
    core = build_core(data, load_config(data), with_signer=False)
    from license_server.core import SessionUser
    r = core.db.conn().execute("SELECT * FROM users WHERE role = 'admin' AND active = 1 ORDER BY id LIMIT 1").fetchone()
    by = SessionUser(r["id"], r["username"], r["display_name"], "admin")
    out = core.register_license(by, Path(args.license).read_text(encoding="utf-8"), plan_code=args.plan,
                                price_cents=args.price, customer_document=args.document)
    _emit({"ok": True, "subscription": {k: out[k] for k in ("license_id", "customer_name", "plan_code", "paid_until",
                                                              "state_label")}})
    return 0


def cmd_evaluate(args) -> int:
    data = Path(args.data)
    core = build_core(data, load_config(data), with_signer=False)
    _emit(core.housekeeping())
    return 0


def cmd_pin(args) -> int:
    from license_server.http import certificate_pin
    data = Path(args.data)
    cfg = load_config(data)
    _emit({"certificate_pin": certificate_pin(data / cfg.get("tls_cert", "tls/cert.pem")), "url": cfg.get("public_url")})
    return 0


def cmd_genkey(args) -> int:
    """Nova chave Ed25519 do servidor (rotação): PEM cifrado + linha pública para o VYONIX DICOM Print."""
    from vyonix_protocol import crypto
    out = Path(args.out)
    if out.exists():
        raise SystemExit(f"Arquivo já existe: {out}")
    pw = _password(args, "Frase-senha da nova chave (mín. 10 caracteres): ")
    k = crypto.generate_ed25519()
    out.write_bytes(crypto.private_to_pem(k, pw.encode()))
    h = crypto.public_hex(k)
    _emit({"ok": True, "file": str(out), "key_id": args.key_id, "public_hex": h, "fingerprint": crypto.fingerprint(h),
           "public_line": f'"{args.key_id}": "{h}",',
           "next": "Acrescente a linha pública (escopo authorization) ao VYONIX DICOM Print em uma atualização "
                   "oficial antes de usar a chave."})
    return 0


def cmd_selftest(args) -> int:
    from license_server.selftest import run
    rep = run()
    rep["frozen"] = bool(getattr(sys, "frozen", False))
    _emit(rep)
    if getattr(args, "report", None):
        Path(args.report).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if rep.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="VYONIX_License_Server", description=f"{APP_NAME} {__version__}")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init", help="configura uma pasta de dados nova")
    s.add_argument("--data", required=True)
    s.add_argument("--admin", required=True)
    s.add_argument("--hostname", action="append", required=True, help="nome/IP público do servidor (repetível)")
    s.add_argument("--port", type=int, default=DEFAULT_PORT)
    s.add_argument("--bind", default="0.0.0.0")
    s.add_argument("--key-file", required=True, help="chave Ed25519 cifrada (.pem) do servidor")
    s.add_argument("--key-id", required=True)
    s.add_argument("--password-file")
    s.set_defaults(fn=cmd_init)
    s = sub.add_parser("serve", help="inicia o servidor HTTPS")
    s.add_argument("--data", required=True)
    s.add_argument("--port", type=int)
    s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("user-add", help="cria usuário (admin, financial, support, viewer)")
    s.add_argument("--data", required=True)
    s.add_argument("--username", required=True)
    s.add_argument("--display-name")
    s.add_argument("--role", required=True, choices=["admin", "financial", "support", "viewer"])
    s.add_argument("--password-file")
    s.set_defaults(fn=cmd_user_add)
    s = sub.add_parser("register", help="registra uma licença (.vylic) emitida pelo License Manager")
    s.add_argument("--data", required=True)
    s.add_argument("--license", required=True)
    s.add_argument("--plan")
    s.add_argument("--price", type=int, help="mensalidade em centavos")
    s.add_argument("--document", help="CNPJ/CPF do cliente")
    s.set_defaults(fn=cmd_register)
    s = sub.add_parser("evaluate", help="avalia vencimentos e carências agora")
    s.add_argument("--data", required=True)
    s.set_defaults(fn=cmd_evaluate)
    s = sub.add_parser("pin", help="mostra a impressão digital do certificado TLS")
    s.add_argument("--data", required=True)
    s.set_defaults(fn=cmd_pin)
    s = sub.add_parser("genkey", help="gera nova chave de assinatura cifrada (rotação)")
    s.add_argument("--out", required=True)
    s.add_argument("--key-id", required=True)
    s.add_argument("--password-file", help="arquivo com a frase-senha")
    s.set_defaults(fn=cmd_genkey)
    s = sub.add_parser("selftest", help="teste de ponta a ponta em pasta temporária (TLS real)")
    s.add_argument("--report", help="grava o resultado em JSON")
    s.set_defaults(fn=cmd_selftest)
    args = p.parse_args(argv)
    try:
        return int(args.fn(args) or 0)
    except Exception as exc:  # noqa: BLE001
        from license_server.core import ServerError
        if isinstance(exc, (ServerError, OSError, ValueError)):
            _emit({"ok": False, "error": str(exc)})
            return 2
        raise


if __name__ == "__main__":
    sys.exit(main())
