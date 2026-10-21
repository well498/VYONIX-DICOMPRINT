"""VYONIX DICOM Print DEMO — 5 dias corridos (120 horas) a partir da primeira ativação.

* Contagem em horário de parede pela linha do tempo do ``TimeIntegrity`` (``max(relógio,
  confiável)``): fechar o programa ou reiniciar o computador não pausa nem reinicia a contagem, e
  voltar o relógio não devolve tempo.
* Elegibilidade **por computador**: o registro da demonstração fica no cofre selado (banco,
  ``%ProgramData%\\VYONIX\\Licensing`` e registro do Windows) — locais que a desinstalação e a
  limpeza de configurações não apagam. Qualquer vestígio (mesmo com selo inválido) impede uma nova
  demonstração local; para outra demonstração, o administrador emite uma **DEMO assinada** pelo
  License Manager (que registra cada Hardware ID que já recebeu DEMO).
* Limite (documentado): sem estado externo confiável, apagar simultaneamente todos os locais do
  cofre com privilégios de administrador, ou restaurar uma imagem de disco anterior, permite
  reiniciar a demonstração local.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from vyonix_protocol.formats import DEMO_HOURS

from app.licensing.vault import Vault
from app.utils.timeutil import from_iso, to_iso

RECORD = "demo"
WARN_BEFORE = timedelta(hours=24)


@dataclass
class DemoState:
    state: str                       # available | active | expired | inconsistent
    started_at: datetime | None = None
    expires_at: datetime | None = None
    remaining: timedelta | None = None
    message: str = ""

    @property
    def warning(self) -> bool:
        return self.state == "active" and self.remaining is not None and self.remaining <= WARN_BEFORE


def _earliest(recs: list[dict[str, Any]]) -> dict[str, Any]:
    return min(recs, key=lambda r: r.get("started_at") or "9999")


class DemoService:
    def __init__(self, vault: Vault) -> None:
        self.vault = vault

    def state(self, now: datetime) -> DemoState:
        rec, rd = self.vault.best(RECORD, _earliest)
        if rec is None:
            if rd.present:
                return DemoState("inconsistent", message="Registro da demonstração adulterado ou de outro "
                                 "computador. A demonstração local não está disponível; solicite uma DEMO "
                                 "assinada ou a licença comercial.")
            return DemoState("available", message="Demonstração de 5 dias (120 horas) disponível.")
        start = from_iso(rec["started_at"])
        end = start + timedelta(hours=int(rec.get("hours", DEMO_HOURS)))
        remaining = end - now
        if remaining.total_seconds() <= 0 or rec.get("ended"):
            return DemoState("expired", start, end, timedelta(0),
                             f"Demonstração encerrada em {end.astimezone():%d/%m/%Y %H:%M}. "
                             "Ative a licença comercial para continuar.")
        return DemoState("active", start, end, remaining,
                         f"Demonstração: restam {fmt_remaining(remaining)} (até {end.astimezone():%d/%m/%Y %H:%M}).")

    def start(self, now: datetime, *, hardware_id: str, hw: dict[str, Any], installation_id: str) -> DemoState:
        cur = self.state(now)
        if cur.state != "available":
            return cur
        self.vault.write(RECORD, {"started_at": to_iso(now), "hours": DEMO_HOURS, "hardware_id": hardware_id,
                                  "hw": hw, "installation_id": installation_id, "origin": "local"})
        return self.state(now)

    def mark_used(self, now: datetime, reason: str) -> None:
        """Revalidação de um cofre adulterado: a demonstração local fica registrada como usada."""
        self.vault.write(RECORD, {"started_at": to_iso(now - timedelta(hours=DEMO_HOURS)), "hours": DEMO_HOURS,
                                  "ended": True, "origin": reason})


def fmt_remaining(td: timedelta) -> str:
    s = max(0, int(td.total_seconds()))
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d} dia(s) e {h} h"
    if h:
        return f"{h} h {m:02d} min"
    return f"{m} min"
