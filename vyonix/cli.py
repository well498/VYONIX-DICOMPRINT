"""Linha de comando do VYONIX Core.

    python -m vyonix init     --admin-url postgresql://postgres@127.0.0.1:5432/postgres --org clinica
    python -m vyonix migrate  (aplica migrações pendentes)
    python -m vyonix serve    (API + interface web, HTTPS)
    python -m vyonix worker   (processador de eventos)
    python -m vyonix status   (diagnóstico sem dados de pacientes)

``init`` cria os papéis e o banco (com o usuário administrador do PostgreSQL informado, que **não**
fica gravado), aplica as migrações, cria a organização e o primeiro administrador e grava
``config.json`` na pasta de dados com as senhas do banco guardadas por ``vyonix.secrets``
(DPAPI no Windows).
"""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from vyonix import __version__
from vyonix import config as config_mod


def _password(env: str, prompt: str) -> str:
    v = os.environ.get(env)
    if v:
        return v
    a = getpass.getpass(prompt)
    if a != getpass.getpass("Repita: "):
        raise SystemExit("As senhas não conferem.")
    return a


def cmd_init(a) -> int:
    from vyonix.db import migrate, provision
    from vyonix.db.session import Database
    from vyonix.secrets import SecretStore
    from vyonix.tenancy import service as tenancy
    data = Path(a.data) if a.data else config_mod.default_data_dir()
    data.mkdir(parents=True, exist_ok=True)
    if (data / "config.json").exists() and not a.force:
        raise SystemExit(f"Já existe {data / 'config.json'}. Use --force para reconfigurar.")
    store = SecretStore(data)
    pw = {r: secrets.token_urlsafe(24) for r in ("owner", "app", "service")}
    urls = provision.provision(a.admin_url, a.db_name, prefix=a.prefix, passwords=pw)
    for r in pw:
        store.put(f"db_{r}", pw[r])
    migrate.upgrade(urls.owner, prefix=a.prefix)
    u = urlsplit(a.admin_url)
    hostport = (u.hostname or "localhost") + (f":{u.port}" if u.port else "")

    def tmpl(role: str) -> str:
        return f"postgresql://{a.prefix}_{role}:{{secret:db_{role}}}@{hostport}/{a.db_name}"
    cfg = {"mode": a.mode, "database_url": tmpl("app"), "service_database_url": tmpl("service"),
           "owner_database_url": tmpl("owner"), "role_prefix": a.prefix, "default_organization": a.org,
           "bind": a.bind, "port": a.port}
    db = Database(urls.app, service_url=urls.service)
    try:
        if tenancy.resolve(db, a.org) is None:
            pwd = _password("VYONIX_ADMIN_PASSWORD", f"Senha do administrador '{a.admin_user}': ")
            tenancy.create_organization(db, code=a.org, name=a.org_name or a.org, admin_username=a.admin_user,
                                        admin_password=pwd, actor="instalação",
                                        register_login=a.mode == "cloud")
            print(f"Organização '{a.org}' e administrador '{a.admin_user}' criados.")
        else:
            print(f"Organização '{a.org}' já existe: mantida.")
    finally:
        db.dispose()
    (data / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"Configuração gravada em {data / 'config.json'} (senhas do banco protegidas, fora do arquivo).")
    return 0


def _cfg(a):
    return config_mod.load(Path(a.data) if a.data else None)


def cmd_migrate(a) -> int:
    from vyonix.db import migrate
    from vyonix.db.session import Database
    from vyonix.tenancy import service as tenancy
    cfg = _cfg(a)
    prefix = cfg.extra.get("role_prefix", "vyonix")
    migrate.upgrade(cfg.owner_database_url, prefix=prefix)
    db = Database(cfg.database_url, service_url=cfg.service_database_url)
    try:
        for tid in tenancy.organizations_for_service(db):
            tenancy.refresh(db, tid)
    finally:
        db.dispose()
    print("Migrações aplicadas:", ", ".join(migrate.current(cfg.owner_database_url)))
    return 0


def ensure_tls(cfg) -> tuple[str, str]:
    """Certificado do servidor: o configurado ou um autoassinado gerado na primeira execução."""
    if cfg.tls_cert and cfg.tls_key:
        return cfg.tls_cert, cfg.tls_key
    d = cfg.data_dir / "tls"
    cert, key = d / "server.crt", d / "server.key"
    if cert.exists() and key.exists():
        return str(cert), str(key)
    import socket
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    d.mkdir(parents=True, exist_ok=True)
    k = ec.generate_private_key(ec.SECP256R1())
    host = socket.gethostname()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"VYONIX {host}")])
    now = datetime.now(timezone.utc)
    import ipaddress
    san = x509.SubjectAlternativeName([x509.DNSName(host), x509.DNSName("localhost"),
                                       x509.IPAddress(ipaddress.ip_address("127.0.0.1"))])
    c = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
         .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
         .not_valid_after(now + timedelta(days=825)).add_extension(san, critical=False)
         .sign(k, hashes.SHA256()))
    key.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()))
    try:
        os.chmod(key, 0o600)
    except OSError:
        pass
    cert.write_bytes(c.public_bytes(serialization.Encoding.PEM))
    return str(cert), str(key)


def cmd_serve(a) -> int:
    import uvicorn
    from vyonix.api.app import create_app
    from vyonix.context import build
    cfg = _cfg(a)
    plat = build(cfg)
    app = create_app(plat, cookie_secure=not a.insecure_http)
    kw = {}
    if not a.insecure_http:
        cert, key = ensure_tls(cfg)
        kw = {"ssl_certfile": cert, "ssl_keyfile": key}
    bind = a.bind or cfg.bind
    if a.insecure_http and bind not in ("127.0.0.1", "localhost"):
        raise SystemExit("HTTP sem TLS só é permitido em 127.0.0.1 (testes).")
    uvicorn.run(app, host=bind, port=a.port or cfg.port, log_level="info", proxy_headers=False,
                server_header=False, **kw)
    return 0


def cmd_worker(a) -> int:
    from vyonix.context import build
    from vyonix.events.worker import build_worker
    cfg = _cfg(a)
    plat = build(cfg)
    w = build_worker(plat)                    # mesmas tarefas periódicas do serviço (ex.: sincronização do PACS)
    logging.getLogger("vyonix").info("Processador de eventos iniciado.")
    try:
        w.run_forever()
    except KeyboardInterrupt:
        w.stop.set()
    return 0


def cmd_status(a) -> int:
    from vyonix.db import migrate
    cfg = _cfg(a)
    out = {"version": __version__, "mode": cfg.mode, "data_dir": str(cfg.data_dir)}
    try:
        out["migrations"] = migrate.current(cfg.owner_database_url)
        out["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        out["database"] = f"erro: {type(exc).__name__}"
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["database"] == "ok" else 1


def _pacs(a):
    from vyonix.context import build
    from vyonix.pacs import backend_for
    from vyonix.tenancy import service as tenancy
    cfg = _cfg(a)
    plat = build(cfg)
    tid = tenancy.resolve(plat.db, a.org or cfg.default_organization)
    if tid is None:
        raise SystemExit("Organização não encontrada.")
    b = backend_for(plat)
    if b is None:
        raise SystemExit("Motor DICOM não configurado (pacs_orthanc_url).")
    return plat, tid, b


def cmd_pacs_backup(a) -> int:
    from vyonix.pacs import backup
    plat, tid, b = _pacs(a)
    out = backup.export(plat.db, tid, b, Path(a.dest), actor="vyonix pacs-backup")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 1 if out["integrity_failures"] else 0


def cmd_pacs_verify(a) -> int:
    from vyonix.pacs import backup
    out = backup.verify(Path(a.src))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["valid"] else 1


def cmd_pacs_restore(a) -> int:
    from vyonix.pacs import backup
    plat, tid, b = _pacs(a)
    out = backup.restore(plat.db, tid, b, Path(a.src), actor="vyonix pacs-restore")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 1 if out["rejected"] else 0


def cmd_homolog_send(a) -> int:
    """Simulador de modalidade (homologação): estudo sintético enviado ao PACS local por C-STORE."""
    from vyonix import homolog
    if not homolog.allowed(a.forcar_teste):
        raise SystemExit("Simulador disponível só no instalador de homologação (ou com --forcar-teste em teste).")
    ds = homolog.synthetic_study(patient_id=a.paciente_id, patient_name=a.nome, issuer=a.emissor,
                                 accession=a.accession or "", modality=a.modalidade.upper(),
                                 description=a.descricao, images=a.imagens)
    r = homolog.send(ds, port=a.porta)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    print("Estudo sintético enviado. Ele aparece na Central de Exames em até 1 minuto (sincronização do PACS)."
          if r["sent"] else "Nenhuma imagem foi aceita pelo PACS.")
    return 0 if r["sent"] and not r["failed"] else 1


def cmd_operator_init(a) -> int:
    """Cria a organização operadora VYONIX (administração global) no servidor em nuvem."""
    from vyonix.context import build
    from vyonix.tenancy import platform_admin
    from vyonix.tenancy import service as tenancy
    cfg = _cfg(a)
    if cfg.edge:
        raise SystemExit("A administração global VYONIX existe só no servidor em nuvem (modo cloud).")
    plat = build(cfg)
    if tenancy.resolve(plat.db, a.code) is not None:
        print(f"Organização '{a.code}' já existe: mantida.")
        return 0
    pwd = _password("VYONIX_OPERATOR_PASSWORD", f"Senha do administrador geral '{a.admin_user}': ")
    platform_admin.create_operator(plat.db, code=a.code, name=a.name, admin_username=a.admin_user,
                                   admin_password=pwd, actor="instalação")
    print(f"Operadora '{a.code}' e administrador geral '{a.admin_user}' criados.")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="vyonix", description=f"VYONIX Core {__version__}")
    p.add_argument("--data", help="pasta de dados (padrão: ProgramData\\VYONIX\\Platform ou /var/lib/vyonix)")
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init", help="cria banco, papéis, organização e administrador")
    i.add_argument("--admin-url", required=True, help="URL de um usuário administrador do PostgreSQL (não é gravada)")
    i.add_argument("--db-name", default="vyonix")
    i.add_argument("--prefix", default="vyonix")
    i.add_argument("--org", required=True, help="código da organização (minúsculas, números e hífen)")
    i.add_argument("--org-name")
    i.add_argument("--admin-user", default="admin")
    i.add_argument("--mode", choices=config_mod.MODES, default="edge")
    i.add_argument("--bind", default="0.0.0.0")
    i.add_argument("--port", type=int, default=8444)
    i.add_argument("--force", action="store_true")
    sub.add_parser("migrate", help="aplica migrações e atualiza catálogos")
    s = sub.add_parser("serve", help="API e interface web")
    s.add_argument("--bind")
    s.add_argument("--port", type=int)
    s.add_argument("--insecure-http", action="store_true", help="somente testes locais (127.0.0.1)")
    sub.add_parser("worker", help="processador de eventos")
    sub.add_parser("status", help="diagnóstico")
    pb = sub.add_parser("pacs-backup", help="backup verificado das imagens do PACS (incremental, não apaga nada)")
    pb.add_argument("--dest", required=True)
    pb.add_argument("--org")
    pv = sub.add_parser("pacs-verify", help="confere um backup do PACS contra o manifesto")
    pv.add_argument("--src", required=True)
    pr = sub.add_parser("pacs-restore", help="restaura um backup do PACS pela entrada normal (idempotente)")
    pr.add_argument("--src", required=True)
    pr.add_argument("--org")
    op = sub.add_parser("operator-init", help="cria a operadora VYONIX (administração global, só modo cloud)")
    op.add_argument("--code", default="vyonix")
    op.add_argument("--name", default="VYONIX")
    op.add_argument("--admin-user", required=True)
    hs = sub.add_parser("homolog-enviar", help="HOMOLOGAÇÃO: envia um estudo sintético ao PACS local (C-STORE)")
    hs.add_argument("--paciente-id", required=True, help="o mesmo identificador cadastrado no paciente fictício")
    hs.add_argument("--nome", required=True, help="nome fictício do paciente (Nome Sobrenome)")
    hs.add_argument("--emissor", default="PRONTUARIO", help="emissor do identificador (padrão do cadastro: PRONTUARIO)")
    hs.add_argument("--accession")
    hs.add_argument("--modalidade", default="CT")
    hs.add_argument("--descricao", default="TC de crânio (sintético)")
    hs.add_argument("--imagens", type=int, default=8)
    hs.add_argument("--porta", type=int, default=4242)
    hs.add_argument("--forcar-teste", action="store_true", help=argparse.SUPPRESS)
    a = p.parse_args(argv)
    return {"init": cmd_init, "migrate": cmd_migrate, "serve": cmd_serve, "worker": cmd_worker,
            "status": cmd_status, "pacs-backup": cmd_pacs_backup, "pacs-verify": cmd_pacs_verify,
            "pacs-restore": cmd_pacs_restore, "operator-init": cmd_operator_init,
            "homolog-enviar": cmd_homolog_send}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
