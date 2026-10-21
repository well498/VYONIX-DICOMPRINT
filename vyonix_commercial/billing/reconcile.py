"""Conciliação de cobranças: notificações do banco e consulta periódica.

Fluxo seguro (testes 11–13):

1. a notificação é registrada pela chave do evento — repetida ⇒ ignorada;
2. a cobrança é localizada no cadastro (desconhecida ⇒ registrada e ignorada);
3. a situação é **consultada no banco** pelo canal autenticado — o conteúdo da notificação não quita;
4. somente ``paid`` confirma o pagamento (idempotente pela referência da cobrança).
"""

from __future__ import annotations

import logging

from vyonix_commercial.billing.base import BillingError, BillingProvider
from vyonix_commercial.engine import Actor, CommercialEngine

log = logging.getLogger(__name__)
BANK = Actor("conciliação bancária", "financial")


def check_charge(engine: CommercialEngine, provider: BillingProvider, charge: dict) -> dict:
    st = provider.charge_status(charge["provider_ref"])
    return engine.update_charge(BANK, charge["id"], status=st.status, provider_status=st.provider_status,
                                paid_cents=st.paid_cents, paid_at=st.paid_at)


def process_webhook(engine: CommercialEngine, provider: BillingProvider, body: bytes) -> list[dict]:
    out = []
    for n in provider.parse_webhook(body):
        if not engine.record_event(provider.name, n.event_key, body.decode("utf-8", "replace")):
            out.append({"ref": n.provider_ref, "result": "repetida (ignorada)"})
            continue
        charge = engine.charge_by_ref(provider.name, n.provider_ref)
        if charge is None:
            engine.set_event_result(provider.name, n.event_key, "cobrança desconhecida")
            out.append({"ref": n.provider_ref, "result": "cobrança desconhecida"})
            continue
        try:
            r = check_charge(engine, provider, charge)
        except BillingError:
            engine.forget_event(provider.name, n.event_key)        # o banco reenviará: tentar de novo
            raise
        res = f"consultada: {r['status']}" + (" — pagamento confirmado" if r.get("payment") else "")
        engine.set_event_result(provider.name, n.event_key, res)
        out.append({"ref": n.provider_ref, "result": res})
    return out


def poll_open_charges(engine: CommercialEngine, provider: BillingProvider) -> list[dict]:
    out = []
    for ch in engine.charges(open_only=True):
        if ch["provider"] != provider.name:
            continue
        try:
            out.append(check_charge(engine, provider, ch))
        except BillingError as exc:
            log.warning("Consulta da cobrança %s falhou: %s", ch["provider_ref"], exc)
            out.append({"charge_id": ch["id"], "error": str(exc)})
    return out
