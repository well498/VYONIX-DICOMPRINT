"""Relatório de compatibilidade a partir do inventário: atendido, alerta ou impeditivo."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from vyonix_deploy.config import DeployConfig
from vyonix_deploy.inventory import port_owner

GB = 1024 ** 3
MIN_BUILD = 17763           # Windows 10 1809 / Server 2019
OWN_PROCESSES = {"postgres", "vyonixplatform", "vyonixservice"}


@dataclass
class Finding:
    id: str
    level: str          # ok | alert | blocker | info
    title: str
    detail: str

    def as_dict(self) -> dict:
        return asdict(self)


def evaluate(inv: dict, cfg: DeployConfig, *, mode: str = "install") -> list[Finding]:
    f: list[Finding] = []
    os_ = inv.get("os", {})
    if inv.get("unsupported"):
        f.append(Finding("os", "blocker", "Sistema operacional", f"Esta fase instala somente no Windows "
                                                                  f"(detectado: {os_.get('caption')})."))
    elif int(os_.get("build") or 0) < MIN_BUILD:
        f.append(Finding("os", "blocker", "Sistema operacional",
                         f"{os_.get('caption')} (build {os_.get('build')}). Mínimo: Windows 10 1809 / Server 2019."))
    else:
        f.append(Finding("os", "ok", "Sistema operacional", f"{os_.get('caption')} (build {os_.get('build')})."))
    if not inv.get("unsupported") and "64" not in str(os_.get("arch", "")):
        f.append(Finding("arch", "blocker", "Arquitetura", f"{os_.get('arch')}: é necessário 64 bits."))
    if mode != "diagnose":
        f.append(Finding("admin", "ok" if inv.get("admin") else "blocker", "Privilégio administrativo",
                         "Executando como administrador." if inv.get("admin") else
                         "Execute o DEPLOY como administrador (necessário para serviços, firewall e ProgramData)."))
    mem = int(inv.get("computer", {}).get("memory") or 0)
    lvl = "blocker" if mem < 4 * GB else ("alert" if mem < 8 * GB else "ok")
    f.append(Finding("memory", lvl, "Memória", f"{mem / GB:.1f} GB (mínimo 4 GB; recomendado 8 GB ou mais)."))
    disks = inv.get("disks", [])
    sysdrive = next((d for d in disks if str(d.get("drive", "")).upper() in ("C:", "/")), disks[0] if disks else None)
    if sysdrive:
        free = int(sysdrive.get("free") or 0)
        lvl = "blocker" if free < 10 * GB else ("alert" if free < 50 * GB else "ok")
        f.append(Finding("disk", lvl, f"Espaço livre em {sysdrive.get('drive')}",
                         f"{free / GB:.1f} GB livres (mínimo 10 GB; recomendado 50 GB, mais o volume de exames)."))
    for name, port in (("HTTPS do VYONIX", cfg.https_port), ("PostgreSQL do VYONIX", cfg.pg_port)):
        own = port_owner(inv, port)
        if own and (own.get("process") or "").lower() not in OWN_PROCESSES:
            f.append(Finding(f"port-{port}", "blocker", f"Porta {port} ({name})",
                             f"Em uso por {own.get('process') or 'outro processo'} (PID {own.get('pid')}). "
                             "Escolha outra porta."))
        elif own:
            f.append(Finding(f"port-{port}", "info", f"Porta {port} ({name})", "Já usada pelo próprio VYONIX."))
        else:
            f.append(Finding(f"port-{port}", "ok", f"Porta {port} ({name})", "Livre."))
    profiles = inv.get("firewall_profiles", [])
    off = [p["name"] for p in profiles if not p.get("enabled")]
    if off:
        f.append(Finding("firewall", "alert", "Firewall do Windows",
                         f"Desligado nos perfis: {', '.join(off)}. O DEPLOY não liga nem desliga o firewall; "
                         "as regras do VYONIX são criadas e valem quando ele estiver ligado."))
    elif profiles:
        f.append(Finding("firewall", "ok", "Firewall do Windows", "Ligado em todos os perfis."))
    if inv.get("reboot_pending"):
        f.append(Finding("reboot", "alert", "Reinicialização pendente",
                         "O Windows aguarda reinicialização (atualizações). Recomenda-se reiniciar antes."))
    others = [s for s in inv.get("services", []) if "postgres" in s["name"].lower()
              and s["name"].lower() != "vyonixpostgresql"]
    if others:
        f.append(Finding("other-postgres", "info", "Outro PostgreSQL no servidor",
                         ", ".join(f"{s['name']} ({s['state']})" for s in others) +
                         ". O VYONIX usa instância própria em outra porta e não altera essa instalação."))
    pacs = [s for s in inv.get("services", []) if any(k in s["name"].lower() for k in ("orthanc", "dcm4", "conquest"))]
    if pacs:
        f.append(Finding("other-pacs", "info", "Outro PACS/servidor DICOM",
                         ", ".join(s["name"] for s in pacs) + ". Confira portas DICOM antes de habilitar o PACS."))
    prev = inv.get("previous", {})
    if prev.get("dicom_print"):
        f.append(Finding("dicom-print", "info", "VYONIX DICOM Print instalado",
                         "Será preservado: o DEPLOY não altera o serviço, os dados nem a licença do DICOM Print."))
    if prev.get("platform_installed") and mode == "install":
        f.append(Finding("previous", "info", "VYONIX já instalado",
                         "Reexecução: cada passo confere o estado atual e só o que faltar será aplicado; dados e "
                         "configurações existentes são preservados. Para nova versão, use Atualizar."))
    return f


def blockers(findings: list[Finding]) -> list[Finding]:
    return [x for x in findings if x.level == "blocker"]
