"""BLK-15 — recusa de equipamentos não autorizados **na associação** (fase simulada, desligada por padrão).

Hoje a política "só equipamentos cadastrados" (``pacs/reception``) retém depois do armazenamento: o motor aceita a
imagem e o CORE a separa para decisão do administrador. A recusa na associação exige que o próprio motor (Orthanc)
conheça a lista de equipamentos autorizados e rode com ``DicomAlwaysAllowStore=false`` (e, opcionalmente,
``DicomCheckModalityHost=true`` para conferir também o IP).

Este módulo só **calcula e aplica a lista** no motor pela API REST (``/modalities``):

* entra todo nó **habilitado** com ``can_store`` (ou destino de C-MOVE com ``can_receive``), com AE, IP e porta;
* as entradas que o VYONIX gerencia têm o prefixo ``vyx-``; entradas manuais de outra origem **nunca** são alteradas;
* nenhuma configuração de instalação existente é alterada aqui: ligar ``DicomAlwaysAllowStore=false`` no motor
  instalado é decisão do proprietário (BLK-15). Os testes usam um Orthanc próprio, iniciado só para o teste.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

PREFIX = "vyx-"
DEFAULT_PORT = 104


def _key(ae: str) -> str:
    return PREFIX + re.sub(r"[^a-z0-9_-]", "_", ae.strip().lower())[:40]


def desired(nodes: Iterable[Any]) -> dict[str, dict[str, Any]]:
    """Nós autorizados → entradas ``/modalities`` do Orthanc (só envio/eco; sem consulta pelo motor)."""
    out: dict[str, dict[str, Any]] = {}
    for n in nodes:
        if not getattr(n, "enabled", True) or not (getattr(n, "can_store", False) or getattr(n, "can_receive", False)):
            continue
        ae = (n.ae_title or "").strip()
        if not ae:
            continue
        out[_key(ae)] = {"AET": ae, "Host": (n.host or "").strip() or "0.0.0.0", "Port": int(n.port or DEFAULT_PORT),
                         "Manufacturer": "Generic", "AllowEcho": True, "AllowStore": bool(n.can_store),
                         "AllowFind": False, "AllowGet": False, "AllowMove": False,
                         "AllowStorageCommitment": False}
    return out


def plan(current: dict[str, dict[str, Any]], want: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """O que mudar: incluir/atualizar entradas ``vyx-``, remover as ``vyx-`` que saíram; o resto fica intacto."""
    def same(a: dict, b: dict) -> bool:
        return all(str(a.get(k)) == str(v) for k, v in b.items() if k != "Manufacturer")
    put = sorted(k for k, v in want.items() if k not in current or not same(current[k], v))
    delete = sorted(k for k in current if k.startswith(PREFIX) and k not in want)
    untouched = sorted(k for k in current if not k.startswith(PREFIX))
    return {"put": put, "delete": delete, "untouched": untouched}


def current(backend) -> dict[str, dict[str, Any]]:
    r = backend._req("GET", "/modalities", params={"expand": ""})
    r.raise_for_status()
    data = r.json()
    if isinstance(data, list):                                 # versões antigas: só os nomes
        return {k: backend._req("GET", f"/modalities/{k}/configuration").json() for k in data}
    return data


def sync(backend, nodes: Iterable[Any], *, dry_run: bool = False) -> dict[str, Any]:
    """Aplica a lista de nós autorizados no motor. ``dry_run`` só devolve o plano."""
    want = desired(nodes)
    cur = current(backend)
    p = plan(cur, want)
    if not dry_run:
        for k in p["put"]:
            backend._req("PUT", f"/modalities/{k}", json=want[k]).raise_for_status()
        for k in p["delete"]:
            backend._req("DELETE", f"/modalities/{k}").raise_for_status()
    return {**p, "dry_run": dry_run, "authorized": sorted(v["AET"] for v in want.values())}
