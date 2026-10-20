"""Ponto de entrada do ``Vyonix.exe``.

Uso::

    python -m app                      # abre a interface
    python -m app --check              # inicializa sem interface e imprime um resumo
    python -m app --data-dir C:\\vyonix-dev   # isola dados (desenvolvimento/testes)
"""

from __future__ import annotations

import argparse
import json
import sys

from app import __version__, brand

EXIT_OK = 0
EXIT_STARTUP_ERROR = 2
EXIT_MISSING_DEPENDENCY = 3
EXIT_ALREADY_RUNNING = 4


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="Vyonix", description=f"{brand.PRODUCT_NAME} — {brand.SLOGAN}")
    p.add_argument("--version", action="version", version=f"{brand.PRODUCT_NAME} {__version__}")
    p.add_argument("--check", action="store_true",
                   help="inicializa diretórios, banco e logs sem abrir a interface")
    p.add_argument("--data-dir", help="pasta isolada para dados (desenvolvimento e testes)")
    p.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                   help="sobrepõe o nível de log configurado nesta execução")
    p.add_argument("--console-log", action="store_true", help="também exibe logs no terminal")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    from app.bootstrap import bootstrap
    from app.core.errors import VyonixError

    if args.check:
        try:
            ctx = bootstrap(data_dir=args.data_dir, role="check", log_level=args.log_level,
                            console_log=args.console_log)
        except VyonixError as exc:
            print(f"ERRO: {exc}", file=sys.stderr)
            return EXIT_STARTUP_ERROR
        try:
            print(json.dumps(ctx.summary(), ensure_ascii=False, indent=2))
        finally:
            ctx.close()
        return EXIT_OK

    try:
        from app.ui.application import run_ui
    except ImportError as exc:
        print(f"ERRO: dependência da interface ausente ({exc}). "
              "Instale com: pip install -r requirements.txt", file=sys.stderr)
        return EXIT_MISSING_DEPENDENCY
    return run_ui(data_dir=args.data_dir, log_level=args.log_level, console_log=args.console_log)


if __name__ == "__main__":
    sys.exit(main())
