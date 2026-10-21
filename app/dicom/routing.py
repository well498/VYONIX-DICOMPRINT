"""Seleção da Regra DICOM de uma associação recebida.

O VYONIX é o **servidor** DICOM: o equipamento é configurado com o IP do computador VYONIX, a porta
e o **AE Title de destino** (Called AE Title) da regra. A regra é escolhida por:

1. **porta de entrada** (listener) + **Called AE Title** — critério principal;
2. **Calling AE Title** — critério adicional opcional (desempate explícito entre regras com o mesmo
   destino; uma regra com Calling AE definido tem precedência sobre a regra "qualquer origem");
3. **IP de origem** — somente restrição opcional (IP ou faixa), nunca necessário para identificar.

Nunca se escolhe a regra pela modalidade. Ambiguidade (duas regras iguais) é recusada com o motivo,
nunca resolvida em silêncio. AE Title e IP **não são autenticação criptográfica** — use também
segmentação de rede/firewall.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.devices.repository import Device
from app.security.validators import ip_allowed

DIAG_CALLING_AE = 0x03
DIAG_CALLED_AE = 0x07


@dataclass(frozen=True)
class RouteResult:
    rule: Device | None
    reason: str
    diagnostic: int = 0
    accepted: bool = False


def select(rules: list[Device], *, port: int, default_port: int, called_ae: str, calling_ae: str,
           address: str) -> RouteResult:
    called = (called_ae or "").strip()
    calling = (calling_ae or "").strip()
    dest = [r for r in rules if (r.called_ae or "").strip() == called and r.effective_port(default_port) == port]
    if not dest:
        return RouteResult(None, f"AE Title de destino '{called}' não configurado na porta {port}",
                           DIAG_CALLED_AE)
    specific = [r for r in dest if r.calling_restriction == calling]
    generic = [r for r in dest if r.calling_restriction is None]
    pool = specific or generic
    if not pool:
        allowed = ", ".join(sorted({r.calling_restriction for r in dest if r.calling_restriction}))
        return RouteResult(None, f"Calling AE '{calling}' não autorizado para o destino '{called}' "
                                 f"(permitidos: {allowed})", DIAG_CALLING_AE)
    if len(pool) > 1:
        # Desempate explícito por restrição de IP (faixas que não se sobrepõem, validadas no cadastro).
        by_ip = [r for r in pool if r.ip_address and ip_allowed(address, r.ip_address)]
        if len(by_ip) == 1:
            pool = by_ip
        elif not by_ip and all(r.ip_address for r in pool):
            return RouteResult(None, f"IP de origem {address} fora das restrições das regras de {called}:{port}",
                               DIAG_CALLING_AE)
    if len(pool) > 1:
        names = ", ".join(f"“{r.name}”" for r in pool)
        return RouteResult(None, f"regras ambíguas para {called}:{port} ({names}); defina um Calling AE "
                                 "Title diferente em cada uma", DIAG_CALLED_AE)
    rule = pool[0]
    if not rule.authorized:
        return RouteResult(rule, f"regra “{rule.name}” desabilitada", DIAG_CALLED_AE)
    if not ip_allowed(address, rule.ip_address):
        return RouteResult(rule, f"IP de origem {address} fora da restrição da regra “{rule.name}” "
                                 f"({rule.ip_address})", DIAG_CALLING_AE)
    return RouteResult(rule, f"regra “{rule.name}”", accepted=True)


def _overlap(a: str | None, b: str | None) -> bool:
    import ipaddress
    if not a or not b:
        return True                     # sem restrição de IP: não serve de desempate
    for x in a.split(","):
        for y in b.split(","):
            try:
                if ipaddress.ip_network(x.strip(), strict=False).overlaps(ipaddress.ip_network(y.strip(), strict=False)):
                    return True
            except ValueError:
                return True
    return False


def conflicts(rules: list[Device], candidate: Device, default_port: int) -> list[Device]:
    """Regras ativas com a mesma combinação porta + Called AE + Calling AE e restrições de IP que se
    sobrepõem (sem critério explícito que as diferencie)."""
    key = (candidate.service, candidate.effective_port(default_port), (candidate.called_ae or "").strip(),
           candidate.calling_restriction)
    return [r for r in rules if r.id != candidate.id and r.active and
            (r.service, r.effective_port(default_port), (r.called_ae or "").strip(), r.calling_restriction) == key
            and _overlap(r.ip_address, candidate.ip_address)]
