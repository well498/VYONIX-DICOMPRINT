"""Dados do Dashboard (§13), lidos do banco — nenhum número é fictício.

Serviços ainda não implementados aparecem explicitamente como "não implementado",
com a fase prevista, em vez de um estado simulado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from app import brand
from app.core.contracts import ServiceState, ServiceStatus
from app.database.repositories.events_repo import EventFilter, EventRecord, EventRepository
from app.database.repositories.stats_repo import RecentDevice, StatsRepository
from app.services.settings_service import SettingsService
from app.utils.timeutil import utc_now


@dataclass(frozen=True)
class Alert:
    level: str          # "info" | "warning" | "error"
    text: str


@dataclass(frozen=True)
class DashboardSnapshot:
    site_name: str
    services: list[ServiceStatus]
    storage_ae: str
    storage_address: str
    storage_port: int
    print_enabled: bool
    print_ae: str
    print_port: int
    devices_total: int
    devices_authorized: int
    recent_devices: list[RecentDevice]
    jobs_received_24h: int
    jobs_in_queue: int
    jobs_spooled_24h: int
    jobs_failed_24h: int
    selected_printer: str
    recent_failures: list[EventRecord]
    alerts: list[Alert] = field(default_factory=list)


class DashboardService:
    def __init__(self, stats: StatsRepository, settings: SettingsService,
                 events: EventRepository,
                 service_status_provider=None, access=None) -> None:
        self.stats = stats
        self.settings = settings
        self.events = events
        # Fase 2+: o provedor real informa o estado dos SCPs.
        self._status_provider = service_status_provider or _not_implemented_status
        self.access = access

    def snapshot(self) -> DashboardSnapshot:
        s = self.settings.get_all()
        failures = self.events.query(EventFilter(
            start=utc_now() - timedelta(hours=24), min_level="ERROR", limit=5))
        services = self._status_provider(s)
        printer = s["printing.default_printer"] or "Não configurada"

        alerts: list[Alert] = [Alert("warning", brand.CLINICAL_DISCLAIMER)]
        if not self.stats.active_license():
            alerts.append(Alert("info", "Licença não ativada. O licenciamento offline será "
                                        "disponibilizado na Fase 8."))
        if self.stats.devices_total() == 0:
            alerts.append(Alert("info", "Nenhum equipamento cadastrado. Cadastre em Equipamentos DICOM."))
        if self.access is not None and not self.access.has_password():
            alerts.append(Alert("warning", "Nenhuma senha de administrador definida: qualquer usuário "
                                           "pode alterar configurações e equipamentos."))
        for st in services:
            if st.state.value == "error":
                alerts.append(Alert("error", f"{st.name}: {st.detail}"))
        if not s["printing.default_printer"]:
            alerts.append(Alert("info", "Nenhuma impressora selecionada (gerenciamento na Fase 4)."))
        for w in self.settings.current_warnings():
            alerts.append(Alert("warning", w))
        if failures:
            alerts.append(Alert("error", f"{len(failures)} falha(s) registrada(s) nas últimas 24 h."))

        return DashboardSnapshot(
            site_name=s["site.name"],
            services=services,
            storage_ae=s["dicom.storage.ae_title"],
            storage_address=s["dicom.storage.bind_address"],
            storage_port=s["dicom.storage.port"],
            print_enabled=s["dicom.print.enabled"],
            print_ae=s["dicom.print.ae_title"],
            print_port=s["dicom.print.port"],
            devices_total=self.stats.devices_total(),
            devices_authorized=self.stats.devices_authorized(),
            recent_devices=self.stats.recent_devices(),
            jobs_received_24h=self.stats.jobs_created_since(24),
            jobs_in_queue=self.stats.jobs_in_queue(),
            jobs_spooled_24h=self.stats.jobs_spooled_since(24),
            jobs_failed_24h=self.stats.jobs_failed_since(24),
            selected_printer=printer,
            recent_failures=failures,
            alerts=alerts,
        )


def _not_implemented_status(_settings) -> list[ServiceStatus]:
    return [
        ServiceStatus("DICOM Storage SCP", ServiceState.NOT_IMPLEMENTED, "Previsto na Fase 2"),
        ServiceStatus("DICOM Print SCP", ServiceState.NOT_IMPLEMENTED, "Previsto na Fase 5"),
        ServiceStatus("Serviço Windows", ServiceState.NOT_IMPLEMENTED, "Previsto na Fase 7"),
    ]
