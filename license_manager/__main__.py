"""Ponto de entrada do VYONIX License Manager (``VYONIX_License_Manager.exe`` ou ``python -m license_manager``).

Opções de linha de comando (o executável é de janela; use ``--report`` para obter o resultado):

* ``--self-test --report r.json [--request arquivo.vyreq]`` — autoteste completo em uma pasta
  temporária: configuração, chave cifrada, cliente, importação da solicitação, emissão, renovação,
  reativação, revogação, backup cifrado e restauração, verificação da auditoria.
* ``--data-dir PASTA`` — pasta de dados explícita.
* ``--version``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import traceback
from pathlib import Path


def _report(path: str | None, data: dict) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    if path:
        Path(path).write_text(text, encoding="utf-8")
    elif sys.stdout is not None:
        print(text)


PEM_KEY = __import__("re").compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----\r?\n[A-Za-z0-9+/=\r\n]{40,}")


def scan_private_keys(folder: Path) -> list[str]:
    """Arquivos que contêm um bloco PEM de chave privada com conteúdo (não apenas o texto do cabeçalho)."""
    hits = []
    if not folder or not folder.is_dir():
        return hits
    for f in folder.rglob("*"):
        try:
            if f.is_file() and f.stat().st_size < 64 * 1024 * 1024 and PEM_KEY.search(f.read_bytes()):
                hits.append(str(f.relative_to(folder)))
        except OSError:
            continue
    return hits


def self_test(request_file: str | None, data_dir: str | None) -> dict:
    from vyonix_protocol import crypto
    from vyonix_protocol import formats as F
    from vyonix_protocol.codec import b64d

    from license_manager import __version__
    from license_manager.paths import LMPaths, exe_dir, resolve
    from license_manager.service import LicenseManager

    checks: list[dict] = []

    def check(name: str, fn) -> None:
        try:
            checks.append({"name": name, "ok": True, "detail": fn()})
        except Exception as exc:  # noqa: BLE001
            checks.append({"name": name, "ok": False, "error": f"{type(exc).__name__}: {exc}",
                           "trace": traceback.format_exc()[-1500:]})

    tmp = Path(data_dir) if data_dir else Path(tempfile.mkdtemp(prefix="vylm-selftest-"))
    state: dict = {}
    try:
        lm = LicenseManager(LMPaths(tmp, "custom"))
        state["lm"] = lm
        pw, kp = "Autoteste-Senha-1", "frase-senha-autoteste"

        def setup():
            state["admin"] = lm.initialize("admin", "Autoteste", pw)
            k = lm.generate_key(state["admin"], "autoteste-01", kp)
            lm.unlock_key(state["admin"], kp)
            state["key"] = k
            state["cid"] = lm.save_customer(state["admin"], {"name": "Clínica Autoteste", "city": "Recife"})
            return f"chave {k['key_id']} {k['fingerprint']}"
        check("configuração, usuário administrador e chave cifrada", setup)

        def key_protected():
            raw = lm.paths.db_file.read_bytes()
            row = lm.db.conn().execute("SELECT private_pem FROM signing_keys").fetchone()[0]
            if not bytes(row).startswith(b"-----BEGIN ENCRYPTED PRIVATE KEY-----") or b"BEGIN PRIVATE KEY" in raw:
                raise RuntimeError("chave privada sem cifra no banco")
            found = scan_private_keys(Path(getattr(sys, "_MEIPASS", ""))) if getattr(sys, "frozen", False) else []
            if found:
                raise RuntimeError(f"bloco de chave privada no pacote do executável: {found[:3]}")
            where = f"; {len(list(Path(sys._MEIPASS).rglob('*')))} arquivos do executável verificados" \
                if getattr(sys, "frozen", False) else ""
            return "PKCS#8 cifrado no banco; nenhuma chave em claro" + where
        check("proteção da chave privada", key_protected)

        def synthetic(tag: str) -> str:
            hw = {"uuid": crypto.tpm_key_digest("ECDSA_P256", tag.encode() + b"u"), "system":
                  crypto.tpm_key_digest("ECDSA_P256", tag.encode() + b"s"), "disk": None, "board": None, "tpm": None,
                  "mac": []}
            data = {"v": F.VERSION, "product_id": F.PRODUCT_ID, "request_id": f"autoteste-{tag}",
                    "hardware_id": F.hardware_id(hw), "hw": hw, "installation_id": f"VYXI-AUTOTESTE-{tag.upper()}",
                    "requested_at": F.iso(__import__("datetime").datetime.now(__import__("datetime").timezone.utc)),
                    "reason": "new", "site": "Autoteste"}
            return F.encode_request(data)

        def issue():
            text = Path(request_file).read_text(encoding="utf-8") if request_file else synthetic("a")
            info = lm.import_request(state["admin"], text)
            lic = lm.issue(state["admin"], info.request_id, state["cid"], ltype="annual", edition="Profissional",
                           max_devices=3, max_printers=2)
            doc = F.parse_signed(lic["document"], F.LICENSE_FORMAT)
            if not crypto.verify_ed25519(state["key"]["public_hex"], doc.signed, doc.signature):
                raise RuntimeError("assinatura não confere")
            if F.validate_license_payload(doc.payload):
                raise RuntimeError("payload inválido")
            state["lic"] = lic
            out = (Path(request_file).resolve().parent if request_file else tmp) / f"{lic['license_id']}.vylic"
            lm.export_license(state["admin"], lic["license_id"], out)
            state["lic_file"] = str(out)
            return f"{lic['license_id']} para {info.data['hardware_id']} / {info.data['installation_id']} (TPM: {info.tpm_status})"
        check("importação da solicitação e emissão assinada", issue)

        def tamper():
            doc = json.loads(state["lic"]["document"])
            p = json.loads(b64d(doc["payload"]))
            p["max_printers"] = 99
            from vyonix_protocol.codec import b64e
            doc["payload"] = b64e(json.dumps(p).encode())
            d = F.parse_signed(json.dumps(doc), F.LICENSE_FORMAT)
            if crypto.verify_ed25519(state["key"]["public_hex"], d.signed, d.signature):
                raise RuntimeError("licença alterada foi aceita")
            return "licença alterada rejeitada pela verificação"
        check("rejeição de licença adulterada", tamper)

        def renew_reactivate():
            r = lm.renew(state["admin"], state["lic"]["license_id"], ltype="annual")
            info2 = lm.import_request(state["admin"], synthetic("b"))
            n = lm.reactivate(state["admin"], r["license_id"], info2.request_id, "disk", "autoteste: troca de disco")
            lm.revoke(state["admin"], n["license_id"], "autoteste")
            rl = lm.revocation_list(state["admin"])
            return f"renovada {r['license_id']}, reativada {n['license_id']}, lista de revogação nº {rl['seq']}"
        check("renovação, reativação e revogação", renew_reactivate)

        def demo():
            info3 = lm.import_request(state["admin"], synthetic("c"))
            d = lm.issue(state["admin"], info3.request_id, state["cid"], ltype="demo", edition="Profissional")
            try:
                lm.issue(state["admin"], info3.request_id, state["cid"], ltype="demo", edition="Profissional")
            except Exception:  # noqa: BLE001
                return f"DEMO {d['license_id']} (120 h); segunda DEMO bloqueada"
            raise RuntimeError("segunda DEMO para o mesmo computador não foi bloqueada")
        check("DEMO assinada e controle de reutilização", demo)

        def backup_restore():
            dest = tmp / "autoteste.vylmbak"
            lm.backup(state["admin"], dest, "frase-do-backup-autoteste")
            if b"Autoteste" in dest.read_bytes():
                raise RuntimeError("backup não cifrado")
            before = len(lm.licenses())
            lm.restore(state["admin"], dest, "frase-do-backup-autoteste")
            after = len(lm.licenses())
            if before != after:
                raise RuntimeError(f"restauração divergente ({before} × {after})")
            return f"{dest.stat().st_size} bytes cifrados; {after} licenças após restaurar"
        check("backup protegido e restauração", backup_restore)

        def audit():
            bad = lm.verify_audit()
            if bad:
                raise RuntimeError(f"auditoria com registros alterados: {bad}")
            return f"{len(lm.audit_log(100000))} registros encadeados"
        check("auditoria encadeada", audit)

        def mode():
            p = resolve()
            return f"modo {p.mode}; dados em {p.root}; executável em {exe_dir()}"
        check("modo de execução e pasta de dados", mode)
    finally:
        if "lm" in state:
            state["lm"].close()
    ok = all(c["ok"] for c in checks)
    out = {"ok": ok, "app": "VYONIX License Manager", "version": __version__, "frozen": bool(getattr(sys, "frozen", False)),
           "executable": sys.executable, "checks": checks, "license_file": state.get("lic_file")}
    if not data_dir:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="VYONIX_License_Manager")
    p.add_argument("--version", action="store_true")
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--request", help="solicitação (.vyreq) usada no autoteste")
    p.add_argument("--report", help="grava o resultado em JSON")
    p.add_argument("--data-dir", help="pasta de dados")
    try:
        args = p.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    from license_manager import APP_NAME, __version__
    if args.version:
        _report(args.report, {"app": APP_NAME, "version": __version__})
        return 0
    if args.self_test:
        r = self_test(args.request, args.data_dir)
        _report(args.report, r)
        return 0 if r["ok"] else 1

    from license_manager.db import DatabaseCorrupt, DatabaseTooNew
    from license_manager.paths import resolve
    from license_manager.service import LicenseManager
    paths = resolve(args.data_dir)
    try:
        lm = LicenseManager(paths)
    except (DatabaseCorrupt, DatabaseTooNew) as exc:
        return _corrupt(paths, exc)
    try:
        from license_manager.ui.main import run_gui
        return run_gui(lm)
    finally:
        lm.close()


def _corrupt(paths, exc) -> int:
    """Banco danificado: oferece a última cópia automática (o arquivo danificado é preservado)."""
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication(sys.argv)
    _ = app
    autos = sorted((paths.backups_dir / "automaticos").glob("license_manager-*.db"))
    if not autos:
        QMessageBox.critical(None, "VYONIX License Manager", f"{exc}\n\nNenhuma cópia automática encontrada. Restaure "
                             "um backup protegido (.vylmbak) depois de mover o arquivo danificado:\n"
                             f"{paths.db_file}")
        return 2
    if QMessageBox.question(None, "VYONIX License Manager", f"{exc}\n\nRestaurar a cópia automática {autos[-1].name}? "
                            "O arquivo danificado será guardado com a extensão .danificado.") != QMessageBox.Yes:
        return 2
    import os
    from datetime import datetime
    shutil.move(str(paths.db_file), str(paths.db_file) + f".{datetime.now():%Y%m%d%H%M%S}.danificado")
    for suffix in ("-wal", "-shm"):
        q = Path(str(paths.db_file) + suffix)
        if q.exists():
            os.remove(q)
    shutil.copy2(autos[-1], paths.db_file)
    QMessageBox.information(None, "VYONIX License Manager", "Cópia restaurada. Abra o License Manager novamente.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
