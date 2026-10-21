"""Portas de escuta (listeners) dos servidores DICOM: a porta padrão do serviço e as portas próprias
das Regras DICOM. Cada porta é um servidor pynetdicom independente do mesmo AE."""

from __future__ import annotations


def listener_ports(devices_repo, service: str, default_port: int) -> list[int]:
    ports = {int(default_port)}
    if devices_repo is not None:
        for r in devices_repo.routes(service):
            if r.authorized and r.listen_port:
                ports.add(int(r.listen_port))
    return sorted(ports)


def start_all(ae, address: str, ports: list[int], handlers, default_port: int):
    """Inicia um servidor por porta. Retorna (servidores {porta: servidor}, erros {porta: OSError})."""
    servers, errors = {}, {}
    for port in ports:
        try:
            servers[port] = ae.start_server((address, port), block=False, evt_handlers=handlers)
        except OSError as exc:
            errors[port] = exc
            if port == default_port:
                break
    return servers, errors


def shutdown_all(servers: dict) -> None:
    for srv in list(servers.values()):
        try:
            srv.shutdown()
        except Exception:  # noqa: BLE001
            pass
