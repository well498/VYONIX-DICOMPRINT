"""Sistema e atualizações (substitui "Licença e módulos" — decisão do proprietário de 04/11/2026).

Somente leitura: versão instalada, situação dos serviços e componentes, banco de dados, cópias de segurança,
histórico de atualizações (do VYONIX DEPLOY), módulos (configuração administrativa) e diagnóstico.
A plataforma não depende de licença; o VYONIX DICOM Print aparece como produto separado, sem controle da licença dele.
Nada aqui altera arquivos, registro ou componentes compartilhados com o DICOM Print.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def _root(plat) -> Path:
    return Path(plat.cfg.data_dir).parent                    # ProgramData\VYONIX


def backups(plat, limit: int = 10) -> dict[str, Any]:
    d = _root(plat) / "Backups"
    items: list[dict[str, Any]] = []
    try:
        for p in sorted((x for x in d.iterdir() if x.is_dir()), reverse=True)[:limit]:
            meta = p / "backup.json"
            info: dict[str, Any] = {"name": p.name}
            if meta.exists():
                try:
                    m = json.loads(meta.read_text(encoding="utf-8"))
                    info.update({k: m.get(k) for k in ("created_at", "reason", "size", "valid") if k in m})
                except (OSError, ValueError):
                    pass
            items.append(info)
        return {"available": True, "count": len(items), "items": items}
    except OSError:
        return {"available": False, "count": 0, "items": [], "message": "Pasta de cópias de segurança não acessível."}


def updates(plat, limit: int = 20) -> dict[str, Any]:
    db = _root(plat) / "Deploy" / "deploy.db"
    try:
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=2)
        try:
            rows = con.execute("SELECT id, kind, status, created_at, updated_at, version, message FROM runs "
                               "ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        finally:
            con.close()
        keys = ("id", "kind", "status", "created_at", "updated_at", "version", "message")
        items = [dict(zip(keys, r)) for r in rows]
        for it in items:
            it["message"] = _clean(it["message"])
        return {"available": True, "items": items}
    except (sqlite3.Error, OSError):
        return {"available": False, "items": [], "message": "Histórico do instalador não acessível por este serviço."}


def database(s: Session) -> dict[str, Any]:
    try:
        ver = str(s.execute(text("SHOW server_version")).scalar() or "").split()[0].split(".")[0]   # só a versão principal
        size = s.execute(text("SELECT pg_database_size(current_database())")).scalar()
        return {"ok": True, "server_version": ver, "size_bytes": int(size or 0)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "problem": type(exc).__name__}


_PATH = re.compile(r"([A-Za-z]:\\[^\s;,'\"]+|/(?:[^\s/;,'\"]+/)+[^\s;,'\"]*)")


def _clean(msg: str | None) -> str | None:
    """Mensagem do DEPLOY sem caminhos internos e curta (não expõe detalhes do servidor)."""
    if not msg:
        return msg
    return _PATH.sub("[caminho]", msg.splitlines()[0])[:200]


def _server_wide_allowed(plat, s: Session) -> bool:
    """No modo cloud o servidor é compartilhado: atualizações, cópias e banco só para a operadora VYONIX."""
    if plat.cfg.mode != "cloud":
        return True
    from vyonix.tenancy.models import Organization
    from sqlalchemy import select
    org = s.execute(select(Organization)).scalar_one_or_none()
    return bool(org and org.kind == "operator")


def overview(plat, s: Session) -> dict[str, Any]:
    from vyonix import __version__, build_flavor, monitoring
    from vyonix.modules import registry
    if not _server_wide_allowed(plat, s):
        hidden = {"available": False, "items": [], "message": "Informação do servidor disponível só para a "
                                                               "administração VYONIX."}
        return {"version": __version__, "flavor": build_flavor.FLAVOR, "mode": plat.cfg.mode,
                "licensing": {"required": False, "message": "A plataforma não usa licença, ativação nem "
                                                            "identificação do computador."},
                "health": monitoring.health_detail(plat, s), "database": {"ok": True},
                "backups": dict(hidden, count=0), "updates": hidden, "modules": registry.listing(s),
                "separate_products": []}
    return {
        "version": __version__, "flavor": build_flavor.FLAVOR, "mode": plat.cfg.mode,
        "licensing": {"required": False,
                      "message": "A plataforma não usa licença, ativação nem identificação do computador."},
        "health": monitoring.health_detail(plat, s),
        "database": database(s),
        "backups": backups(plat),
        "updates": updates(plat),
        "modules": registry.listing(s),
        "separate_products": [{"name": "VYONIX DICOM Print",
                               "note": "Produto separado, com licenciamento próprio; a plataforma não controla nem "
                                       "depende dessa licença."}],
    }
