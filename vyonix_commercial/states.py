"""Estados comerciais da assinatura — cálculo único, usado pelo License Manager, pelo License Server e
pelo VYONIX DICOM Print (que recebe os dados assinados na autorização de uso).

O cálculo depende só das datas da assinatura e do horário informado; nada aqui consulta rede ou
banco. Assim o VYONIX chega à mesma conclusão que o servidor, mesmo sem internet.

Ordem de avaliação::

    permanente ........................................... ATIVA (nunca suspensa por mensalidade)
    suspensão aplicada (após a última reativação) ......... SUSPENSA
    suspensão programada: antes da data .................. SUSPENSÃO PROGRAMADA / depois: SUSPENSA
    após a carência ...................................... EXPIRADA (ou SUSPENSA, se a política
                                                           contratual prevê suspensão automática)
    vencida, dentro da carência .......................... EM ATRASO
    reativada há poucos dias ............................. REATIVADA
    a menos de N dias do vencimento ...................... PRÓXIMA DO VENCIMENTO
    demais casos ......................................... ATIVA
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


class CommercialState(str, enum.Enum):
    ACTIVE = "active"
    DUE_SOON = "due_soon"
    OVERDUE = "overdue"
    SUSPENSION_SCHEDULED = "suspension_scheduled"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    REACTIVATED = "reactivated"

    @property
    def label(self) -> str:
        return STATE_LABELS[self.value]

    @property
    def restricts(self) -> bool:
        return self in (CommercialState.SUSPENDED, CommercialState.EXPIRED)


STATE_LABELS = {
    "active": "ATIVA", "due_soon": "PRÓXIMA DO VENCIMENTO", "overdue": "EM ATRASO",
    "suspension_scheduled": "SUSPENSÃO PROGRAMADA", "suspended": "SUSPENSA", "expired": "EXPIRADA",
    "reactivated": "REATIVADA",
}
REACTIVATED_DISPLAY = timedelta(days=3)
USER_NOTICE = ("Funções licenciadas suspensas nesta instalação. Os exames e as configurações estão preservados. "
               "Procure o administrador da clínica.")


def parse(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    v = str(value).strip()
    if len(v) == 10:
        from vyonix_protocol.formats import parse_time
        return parse_time(v)
    dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def local(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    from vyonix_protocol.formats import BRT
    return dt.astimezone(BRT).strftime("%d/%m/%Y %H:%M")


@dataclass(frozen=True)
class Evaluation:
    state: CommercialState
    due_at: datetime | None = None              # vencimento (fim do período pago)
    grace_until: datetime | None = None         # fim da carência (já com prorrogações)
    suspend_at: datetime | None = None          # suspensão programada
    since: datetime | None = None               # início da restrição (SUSPENSA/EXPIRADA)
    days_overdue: int = 0
    days_to_due: int | None = None
    admin_message: str = ""                     # detalhe comercial: só para o administrador
    user_message: str | None = None             # aviso neutro para os demais usuários
    automatic: bool = False                     # suspensão automática pela política contratual

    @property
    def restricts(self) -> bool:
        return self.state.restricts

    @property
    def label(self) -> str:
        return self.state.label

    def as_dict(self) -> dict[str, Any]:
        return {"state": self.state.value, "label": self.label, "restricts": self.restricts,
                "due_at": iso(self.due_at), "grace_until": iso(self.grace_until), "suspend_at": iso(self.suspend_at),
                "since": iso(self.since), "days_overdue": self.days_overdue, "days_to_due": self.days_to_due,
                "admin_message": self.admin_message, "user_message": self.user_message, "automatic": self.automatic}


def grace_end(snapshot: dict[str, Any]) -> datetime | None:
    due = parse(snapshot.get("paid_until"))
    if due is None:
        return None
    end = due + timedelta(days=int(snapshot.get("grace_days") or 0))
    extra = parse(snapshot.get("grace_extra_until"))
    return max(end, extra) if extra else end


def evaluate(snapshot: dict[str, Any], now: datetime) -> Evaluation:
    """Estado comercial em ``now`` a partir dos dados da assinatura (dicionário do snapshot)."""
    now = now.astimezone(timezone.utc)
    reactivated = parse(snapshot.get("reactivated_at"))
    recently = bool(reactivated and timedelta(0) <= now - reactivated < REACTIVATED_DISPLAY)
    if snapshot.get("permanent"):
        st = CommercialState.REACTIVATED if recently else CommercialState.ACTIVE
        note = "Licença permanente: não é suspensa por mensalidade."
        maint = parse(snapshot.get("maintenance_until"))
        if maint is not None and now >= maint:
            note += f" Manutenção opcional encerrada em {local(maint)} (não afeta o funcionamento)."
        return Evaluation(st, admin_message=note)
    due = parse(snapshot.get("paid_until"))
    if due is None:
        return Evaluation(CommercialState.EXPIRED, since=now, admin_message="Assinatura sem período pago registrado.",
                          user_message=USER_NOTICE)
    g_end = grace_end(snapshot) or due
    warn = timedelta(days=int(snapshot.get("warn_days") or 0))
    days_over = max(0, (now - due).days + (1 if now >= due else 0)) if now >= due else 0
    days_to = max(0, (due - now).days) if now < due else None
    common = dict(due_at=due, grace_until=g_end, days_overdue=days_over, days_to_due=days_to)
    suspended_at = parse(snapshot.get("suspended_at"))
    if suspended_at is not None and now >= suspended_at and not (reactivated and reactivated > suspended_at):
        reason = snapshot.get("suspension_reason") or "inadimplência confirmada"
        return Evaluation(CommercialState.SUSPENDED, since=suspended_at, **common,
                          admin_message=f"Assinatura suspensa em {local(suspended_at)} ({reason}). Regularize para "
                                        "reativar; imagens, filas e configurações estão preservadas.",
                          user_message=USER_NOTICE)
    suspend_at = parse(snapshot.get("suspend_at"))
    if suspend_at is not None and not (reactivated and reactivated > suspend_at):
        if now >= suspend_at:
            return Evaluation(CommercialState.SUSPENDED, since=suspend_at, suspend_at=suspend_at, **common,
                              admin_message=f"Suspensão programada aplicada em {local(suspend_at)} (mensalidade "
                                            f"vencida em {local(due)}). Regularize para reativar.",
                              user_message=USER_NOTICE)
        return Evaluation(CommercialState.SUSPENSION_SCHEDULED, suspend_at=suspend_at, **common,
                          admin_message=f"Suspensão programada para {local(suspend_at)}: mensalidade vencida em "
                                        f"{local(due)}. Regularize antes dessa data para evitar a suspensão.")
    if now >= g_end:
        if snapshot.get("auto_suspend"):
            return Evaluation(CommercialState.SUSPENDED, since=g_end, automatic=True, **common,
                              admin_message=f"Suspensa automaticamente ao fim da carência ({local(g_end)}), conforme "
                                            "a política contratual. Regularize para reativar.",
                              user_message=USER_NOTICE)
        return Evaluation(CommercialState.EXPIRED, since=g_end, **common,
                          admin_message=f"Prazo de autorização encerrado em {local(g_end)} (vencimento "
                                        f"{local(due)}). Renove a assinatura ou importe o arquivo de renovação.",
                          user_message=USER_NOTICE)
    if now >= due:
        return Evaluation(CommercialState.OVERDUE, **common,
                          admin_message=f"Mensalidade vencida em {local(due)} ({days_over} dia(s) em atraso). "
                                        f"Funcionamento normal durante a carência, até {local(g_end)}.")
    if recently:
        return Evaluation(CommercialState.REACTIVATED, **common,
                          admin_message=f"Assinatura reativada em {local(reactivated)}. Próximo vencimento: "
                                        f"{local(due)}.")
    if now >= due - warn:
        return Evaluation(CommercialState.DUE_SOON, **common,
                          admin_message=f"A assinatura vence em {local(due)} ({days_to} dia(s)).")
    return Evaluation(CommercialState.ACTIVE, **common, admin_message=f"Assinatura em dia até {local(due)}.")


SNAPSHOT_KEYS = ("permanent", "paid_until", "warn_days", "grace_days", "grace_extra_until", "suspend_at",
                 "suspended_at", "suspension_reason", "auto_suspend", "reactivated_at", "maintenance_until", "plan")
