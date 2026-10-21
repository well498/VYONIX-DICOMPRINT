"""VYONIX Installation ID — identidade de cada instalação e distinção atualização × reinstalação.

Como a distinção é feita (não depende só da presença de um arquivo):

1. **Programa de instalação** (Inno Setup): antes de copiar os arquivos, ele consulta a entrada de
   desinstalação do Windows do produto (``HKLM\\...\\Uninstall\\{AppId}_is1``), mantida pelo próprio
   Windows/instalador. Existe → **atualização** (``--installation install --upgrade``); não existe →
   **instalação nova** (``--fresh``).
2. **Registro selado da instalação** no cofre (``vault.py``: banco, ProgramData e registro do
   Windows, com selo HMAC protegido pelo DPAPI da máquina), com estado ``active``/``uninstalled``.
3. **Desinstalação** (``--installation uninstall``, executado pelo desinstalador): encerra a
   ativação local (licenças ``ended``), marca a instalação como ``uninstalled`` e guarda o ID na
   lista de IDs aposentados.

Instalação nova → sempre um ID novo (o ID anterior é aposentado), mesmo que os dados antigos tenham
sido mantidos: a licença anterior deixa de corresponder e uma nova solicitação é exigida.
Atualização → o ID ativo é preservado (licença, ativação e configurações continuam valendo).
Sem registro ativo em tempo de execução (cópia manual da pasta, cofre removido) → ID novo.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Callable

from app.licensing.vault import Vault
from app.utils.timeutil import utc_now_iso

RECORD = "installation"


def new_installation_id() -> str:
    return "VYXI-" + str(uuid.uuid4()).upper()


@dataclass
class Installation:
    installation_id: str
    state: str
    created_at: str
    origin: str
    retired: list[str]
    tampered: list[str]


class InstallationManager:
    def __init__(self, vault: Vault, *, now: Callable[[], str] = utc_now_iso,
                 on_new: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.vault = vault
        self.now = now
        self.on_new = on_new

    def _record(self) -> tuple[dict[str, Any] | None, list[str]]:
        rec, rd = self.vault.best(RECORD)
        return rec, rd.tampered

    def _make(self, prev: dict[str, Any] | None, origin: str, *, adopt: str | None = None) -> dict[str, Any]:
        retired = list((prev or {}).get("retired") or [])
        if prev and prev.get("installation_id") and prev["installation_id"] not in retired \
                and prev["installation_id"] != adopt:
            retired.append(prev["installation_id"])
        rec = {"installation_id": adopt or new_installation_id(), "state": "active", "created_at": self.now(),
               "origin": origin, "retired": retired[-50:], "seq": int((prev or {}).get("seq", 0))}
        self.vault.write(RECORD, rec)
        if self.on_new:
            self.on_new(rec)
        return rec

    def current(self) -> Installation:
        rec, tampered = self._record()
        if not rec or rec.get("state") != "active":
            rec = self._make(rec, "runtime")
        return Installation(rec["installation_id"], rec["state"], rec["created_at"], rec.get("origin", ""),
                            list(rec.get("retired") or []), tampered)

    def provision(self, mode: str, legacy_id: str | None = None) -> tuple[dict[str, Any], str]:
        """Chamado pelo instalador. ``mode``: ``fresh`` ou ``upgrade``. Retorna (registro, descrição)."""
        rec, _ = self._record()
        if mode == "upgrade":
            if rec and rec.get("state") == "active":
                return rec, "atualização: Installation ID preservado"
            if legacy_id and not (rec and legacy_id in (rec.get("retired") or [])):
                # Atualização a partir da 1.0.0 (antes do cofre): adota o ID do banco existente.
                return self._make(rec, "upgrade-legacy", adopt=legacy_id), "atualização: ID da versão anterior adotado"
            return self._make(rec, "upgrade-without-record"), "atualização sem registro ativo: novo Installation ID"
        if mode == "fresh":
            return self._make(rec, "installer"), "instalação nova: novo Installation ID"
        raise ValueError(f"modo desconhecido: {mode}")

    def uninstall(self) -> dict[str, Any] | None:
        rec, _ = self._record()
        if not rec:
            return None
        rec = dict(rec)
        retired = list(rec.get("retired") or [])
        if rec.get("installation_id") and rec["installation_id"] not in retired:
            retired.append(rec["installation_id"])
        rec.update(state="uninstalled", uninstalled_at=self.now(), retired=retired[-50:])
        self.vault.write(RECORD, rec)
        return rec
