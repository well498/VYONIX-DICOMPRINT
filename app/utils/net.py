"""Endereços IPv4 deste computador (para a tela "Configurar destino no equipamento")."""

from __future__ import annotations

import ipaddress
import socket
from functools import lru_cache


def _primary() -> str | None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))           # não envia pacotes: só escolhe a interface de saída
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def local_ipv4_addresses() -> list[str]:
    """IPs IPv4 não-loopback, o principal primeiro."""
    found: list[str] = []
    prim = _primary()
    if prim:
        found.append(prim)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in found:
                found.append(ip)
    except OSError:
        pass
    return [ip for ip in found if not ipaddress.ip_address(ip).is_loopback and not ip.startswith("169.254.")]


@lru_cache(maxsize=1)
def _cached() -> tuple[str, ...]:
    return tuple(local_ipv4_addresses())


def all_local_addresses() -> frozenset[str]:
    return frozenset({"127.0.0.1", "::1", *_cached()})


def best_server_address(bind_address: str, peer_hint: str | None = None) -> tuple[str | None, list[str]]:
    """IP que o equipamento deve usar. Com várias interfaces, prefere a da mesma rede do equipamento
    (``peer_hint``: IP ou faixa da restrição da regra, ou último IP visto)."""
    if bind_address and bind_address not in ("0.0.0.0", "::"):
        return bind_address, [bind_address]
    ips = local_ipv4_addresses()
    if peer_hint:
        try:
            net = ipaddress.ip_network(peer_hint.split(",")[0].strip(), strict=False)
            peer = net.network_address
            for prefix in (net.prefixlen if net.prefixlen < 32 else 24, 16):
                for ip in ips:
                    if ipaddress.ip_address(ip) in ipaddress.ip_network(f"{peer}/{prefix}", strict=False):
                        return ip, ips
        except ValueError:
            pass
    return (ips[0] if ips else None), ips
