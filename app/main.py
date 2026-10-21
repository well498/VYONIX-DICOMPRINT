"""Ponto de entrada do ``Vyonix.exe``.

Uso::

    Vyonix.exe                              # abre a interface
    Vyonix.exe --check                      # inicializa sem interface e imprime um resumo
    Vyonix.exe --check --report out.json    # idem, gravando o resumo em arquivo
    Vyonix.exe --smoke-test --report r.json # abre a janela, percorre as páginas e fecha
    Vyonix.exe --data-dir C:\\vyonix-dev     # isola dados (desenvolvimento/testes)

O executável empacotado não tem console (``sys.stdout`` é ``None``); por isso toda
saída de texto passa por ``_emit`` e os modos automatizados aceitam ``--report``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app import __version__, brand

EXIT_OK = 0
EXIT_SMOKE_FAILED = 1
EXIT_STARTUP_ERROR = 2
EXIT_MISSING_DEPENDENCY = 3
EXIT_ALREADY_RUNNING = 4


def _emit(text: str, *, error: bool = False) -> None:
    stream = sys.stderr if error else sys.stdout
    if stream is not None:
        try:
            print(text, file=stream)
        except (OSError, ValueError):
            pass


def _write_report(path: str | None, payload: dict) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _service_check(args) -> int:
    """Consulta o serviço pelo canal de controle e testa os servidores dele com C-ECHO."""
    from app.dicom import scu
    from app.dicom.association_manager import SELFTEST_AE
    from app.service.ipc import IpcClient
    from app.service.remote import windows_service_state
    from app.utils.paths import resolve_paths
    paths = resolve_paths(args.data_dir)
    scm_state, scm_text = windows_service_state()
    report: dict = {"ok": False, "scm": scm_state, "scm_detail": scm_text}
    try:
        status = IpcClient(paths.machine_root, timeout=10).call("status")
        report["status"] = status
        echoes = {}
        for key, ae_key in (("storage_bound", "dicom.storage.ae_title"), ("print_bound", "dicom.print.ae_title")):
            bound = status.get(key)
            if bound:
                host = "127.0.0.1" if bound[0] in ("0.0.0.0", "") else bound[0]
                from app.bootstrap import bootstrap
                ae = None
                ctx = bootstrap(data_dir=args.data_dir, role="check")
                try:
                    ae = ctx.settings.get(ae_key)
                finally:
                    ctx.close()
                echoes[key] = scu.echo(host, int(bound[1]), ae, calling_ae=SELFTEST_AE, timeout=10)
        report["echo"] = echoes
        states = {s["name"]: s["state"] for s in status["services"]}
        report["ok"] = (states.get("DICOM Storage SCP") == "running" and states.get("Fila de impressão") == "running"
                        and all(e.get("ok") for e in echoes.values()) and bool(echoes))
    except Exception as exc:  # noqa: BLE001
        report["error"] = str(exc)
    _emit(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    _write_report(args.report, report)
    return EXIT_OK if report["ok"] else EXIT_STARTUP_ERROR


def _backup_cli(args) -> int:
    from app.core.errors import VyonixError
    from app.database.migrations import MIGRATIONS
    from app.service.ipc import IpcClient
    from app.services import backup as bk
    from app.utils.paths import resolve_paths
    paths = resolve_paths(args.data_dir)
    report: dict = {"ok": False}
    try:
        if args.restore_backup:
            if IpcClient(paths.machine_root, timeout=3).available():
                raise VyonixError("O serviço Windows do VYONIX está em execução. Pare-o (sc stop VyonixDicomPrint) e "
                                  "feche a janela do VYONIX antes de restaurar.")
            lock = paths.user_root / "vyonix-ui.lock"
            previous = bk.restore(Path(args.restore_backup), paths.database_file, paths.backups_dir,
                                  max_schema=MIGRATIONS[-1].version)
            report.update(ok=True, restored_from=str(args.restore_backup), previous_saved_as=str(previous),
                          warning="Feche outras janelas do VYONIX antes; depois inicie o serviço (sc start "
                                  "VyonixDicomPrint)." if lock.exists() else "")
        else:
            from app.bootstrap import bootstrap
            ctx = bootstrap(data_dir=args.data_dir, role="check")
            try:
                target = ctx.backups.create(actor="cli", label="manual")
            finally:
                ctx.close()
            report.update(ok=True, backup=str(target))
    except (VyonixError, OSError) as exc:
        report["error"] = str(exc)
    _emit(json.dumps(report, ensure_ascii=False, indent=2))
    _write_report(args.report, report)
    return EXIT_OK if report["ok"] else EXIT_STARTUP_ERROR


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="Vyonix", description=f"{brand.PRODUCT_NAME} — {brand.SLOGAN}")
    p.add_argument("--version", action="store_true", help="mostra a versão e sai")
    p.add_argument("--check", action="store_true",
                   help="inicializa diretórios, banco e logs sem abrir a interface")
    p.add_argument("--smoke-test", action="store_true",
                   help="abre a interface, percorre todas as páginas, salva uma configuração e fecha")
    p.add_argument("--tray", action="store_true",
                   help="inicia só com o ícone na bandeja (usado ao entrar no Windows)")
    p.add_argument("--service-check", action="store_true",
                   help="verifica o serviço Windows: canal de controle, estado e C-ECHO dos servidores")
    p.add_argument("--backup-now", action="store_true", help="cria um backup do banco de dados e sai")
    p.add_argument("--restore-backup", metavar="ARQUIVO",
                   help="restaura o banco a partir de um backup (pare o serviço Windows antes; requer administrador)")
    p.add_argument("--report", help="grava o resultado de --check/--smoke-test neste arquivo JSON")
    p.add_argument("--data-dir", help="pasta isolada para dados (desenvolvimento e testes)")
    p.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                   help="sobrepõe o nível de log configurado nesta execução")
    p.add_argument("--console-log", action="store_true", help="também exibe logs no terminal")
    from app.licensing.cli import add_arguments
    add_arguments(p)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse sem console não pode derrubar o processo silenciosamente
        return int(exc.code or 0)

    if args.version:
        _emit(f"{brand.PRODUCT_NAME} {__version__}")
        _write_report(args.report, {"version": __version__})
        return EXIT_OK

    console = args.console_log and sys.stderr is not None

    from app.bootstrap import bootstrap
    from app.core.errors import VyonixError

    if args.service_check:
        return _service_check(args)
    if args.backup_now or args.restore_backup:
        return _backup_cli(args)
    if args.installation or args.license_action:
        from app.licensing.cli import run as license_cli
        return license_cli(args)

    if args.check:
        try:
            ctx = bootstrap(data_dir=args.data_dir, role="check", log_level=args.log_level,
                            console_log=console)
        except VyonixError as exc:
            _emit(f"ERRO: {exc}", error=True)
            _write_report(args.report, {"ok": False, "error": str(exc)})
            return EXIT_STARTUP_ERROR
        try:
            summary = {"ok": True, **ctx.summary()}
            _emit(json.dumps(summary, ensure_ascii=False, indent=2))
            _write_report(args.report, summary)
        finally:
            ctx.close()
        return EXIT_OK

    try:
        from app.ui.application import run_ui
    except ImportError as exc:
        _emit(f"ERRO: dependência da interface ausente ({exc}). "
              "Instale com: pip install -r requirements.txt", error=True)
        _write_report(args.report, {"ok": False, "error": f"ImportError: {exc}"})
        return EXIT_MISSING_DEPENDENCY
    return run_ui(data_dir=args.data_dir, log_level=args.log_level, console_log=console,
                  smoke_test=args.smoke_test, report=args.report, tray_start=args.tray)


if __name__ == "__main__":
    sys.exit(main())
