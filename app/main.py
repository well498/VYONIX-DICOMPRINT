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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="Vyonix", description=f"{brand.PRODUCT_NAME} — {brand.SLOGAN}")
    p.add_argument("--version", action="store_true", help="mostra a versão e sai")
    p.add_argument("--check", action="store_true",
                   help="inicializa diretórios, banco e logs sem abrir a interface")
    p.add_argument("--smoke-test", action="store_true",
                   help="abre a interface, percorre todas as páginas, salva uma configuração e fecha")
    p.add_argument("--report", help="grava o resultado de --check/--smoke-test neste arquivo JSON")
    p.add_argument("--data-dir", help="pasta isolada para dados (desenvolvimento e testes)")
    p.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                   help="sobrepõe o nível de log configurado nesta execução")
    p.add_argument("--console-log", action="store_true", help="também exibe logs no terminal")
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
                  smoke_test=args.smoke_test, report=args.report)


if __name__ == "__main__":
    sys.exit(main())
