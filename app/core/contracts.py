"""Contratos de comunicação entre os módulos do VYONIX.

Cada módulo de domínio implementa um destes protocolos; os demais módulos dependem
apenas do protocolo, nunca da implementação concreta. Isso permite:

* testar cada módulo isoladamente com implementações falsas;
* mover o núcleo para o serviço Windows (Fase 7) sem alterar a interface;
* substituir componentes (ex.: backend de impressão) sem reescrever o restante.

Regra de privacidade: DTOs carregam somente identificadores técnicos (UIDs, AE Title,
modalidade). Dados demográficos do paciente permanecem no arquivo DICOM original.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Protocol, Sequence, runtime_checkable


# ---------------------------------------------------------------------------
# Estado de serviços
# ---------------------------------------------------------------------------
class ServiceState(str, enum.Enum):
    NOT_IMPLEMENTED = "not_implemented"
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass(frozen=True)
class ServiceStatus:
    name: str
    state: ServiceState
    detail: str = ""
    since: datetime | None = None


@runtime_checkable
class DicomService(Protocol):
    """Servidor DICOM (Storage SCP — Fase 2; Print SCP — Fase 5)."""

    def start(self) -> None: ...
    def stop(self, timeout: float = 10.0) -> None: ...
    def status(self) -> ServiceStatus: ...


# ---------------------------------------------------------------------------
# Recepção DICOM
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AssociationPeer:
    calling_ae: str
    called_ae: str
    address: str
    port: int


@dataclass(frozen=True)
class ReceivedInstance:
    """Instância armazenada pelo Storage SCP. O arquivo original é imutável."""

    sop_instance_uid: str
    sop_class_uid: str
    study_uid: str
    series_uid: str
    modality: str
    transfer_syntax: str
    file_path: Path
    file_sha256: str
    peer: AssociationPeer
    device_id: int | None
    received_at: datetime
    duplicate: bool = False


@runtime_checkable
class InstanceSink(Protocol):
    def on_instance_received(self, instance: ReceivedInstance) -> None: ...


@dataclass(frozen=True)
class PrintRequest:
    """Pedido de impressão consolidado a partir do DICOM Print Management.

    ``film_session`` e ``film_box`` contêm os atributos recebidos (Film Size ID,
    Image Display Format, Film Orientation, Magnification Type, ...), exatamente
    como negociados — a interpretação fica com o motor de regras.
    """

    peer: AssociationPeer
    film_session: Mapping[str, Any]
    film_box: Mapping[str, Any]
    image_boxes: Sequence[Mapping[str, Any]]
    device_id: int | None
    received_at: datetime


@runtime_checkable
class PrintRequestSink(Protocol):
    def on_print_request(self, request: PrintRequest) -> None: ...


# ---------------------------------------------------------------------------
# Resolução de configurações (§10 — exibir a origem de cada configuração)
# ---------------------------------------------------------------------------
class SettingOrigin(str, enum.Enum):
    DICOM_PRINT = "dicom_print"   # recebido do equipamento via Print Management
    RULE = "rule"                 # regra automática
    CUSTOM = "custom"             # preferência personalizada do cliente
    PROFILE = "profile"           # perfil de impressão associado
    DEFAULT = "default"           # padrão geral do sistema


@dataclass(frozen=True)
class ResolvedSetting:
    value: Any
    origin: SettingOrigin
    reference: str | None = None  # ex.: "rule:12", "profile:3"


@dataclass(frozen=True)
class ResolvedPrintSettings:
    printer: ResolvedSetting
    paper_size: ResolvedSetting
    orientation: ResolvedSetting
    layout: ResolvedSetting
    copies: ResolvedSetting
    profile_id: ResolvedSetting
    extras: Mapping[str, ResolvedSetting] = field(default_factory=dict)
    hold_for_review: bool = False
    require_confirmation: bool = False


@dataclass(frozen=True)
class RuleContext:
    """Dados disponíveis para avaliação de regras."""

    calling_ae: str
    device_id: int | None
    modality: str | None
    site: str | None
    printer_hint: str | None
    study_description: str | None
    received_at: datetime
    dicom_print: PrintRequest | None = None


@runtime_checkable
class RulesEngine(Protocol):
    def resolve(self, context: RuleContext) -> ResolvedPrintSettings: ...
    def simulate(self, context: RuleContext) -> list[str]:
        """Explica, passo a passo, quais regras casariam e por quê."""
        ...


# ---------------------------------------------------------------------------
# Imagem
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PresentationParams:
    """Parâmetros explícitos de apresentação. Nada é aplicado implicitamente."""

    frame_index: int = 0
    window_center: float | None = None
    window_width: float | None = None
    voi_lut_index: int | None = None
    invert: bool = False
    brightness: float = 0.0
    contrast: float = 1.0
    gamma: float = 1.0
    rotate_degrees: int = 0
    flip_horizontal: bool = False
    flip_vertical: bool = False
    crop: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class RenderedImage:
    pixels: Any                    # numpy.ndarray (uint8, HxW ou HxWx3)
    photometric: str               # "MONOCHROME2" ou "RGB" após o pipeline
    pixel_spacing_mm: tuple[float, float] | None
    applied: Mapping[str, Any]     # parâmetros efetivamente aplicados (rastreabilidade)


@runtime_checkable
class ImagePipeline(Protocol):
    def render(self, source: Path, params: PresentationParams) -> RenderedImage: ...


# ---------------------------------------------------------------------------
# Layout e impressão
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PageSpec:
    paper_size: str                # "A4", "A3", "Letter", "Legal" ou nome do driver
    width_mm: float
    height_mm: float
    orientation: str               # "portrait" | "landscape"
    rows: int
    columns: int
    margins_mm: tuple[float, float, float, float]   # topo, direita, base, esquerda
    spacing_mm: float = 2.0
    dpi: int = 300                 # DPI de SAÍDA, nunca a resolução da imagem médica
    preserve_aspect: bool = True


@dataclass(frozen=True)
class ComposedPage:
    index: int
    pixels: Any
    dpi: int


@runtime_checkable
class LayoutEngine(Protocol):
    def compose(self, images: Sequence[RenderedImage], page: PageSpec) -> list[ComposedPage]: ...


@dataclass(frozen=True)
class PrinterInfo:
    name: str
    driver: str
    is_default: bool
    paper_sizes: Sequence[str]
    resolutions_dpi: Sequence[int]
    supports_color: bool | None
    status_text: str
    backend: str = "windows"        # "windows" (spooler) ou "pdf" (arquivo gerado pelo VYONIX)
    port: str = ""
    available: bool = True


@dataclass(frozen=True)
class SpoolRequest:
    """Pedido ao backend. ``pages`` é uma fábrica: cada chamada gera as páginas de novo, uma por
    vez (permite repetir cópias quando o driver não as suporta, sem manter todas em memória)."""

    printer: str
    document_name: str
    pages: Callable[[], Iterator[ComposedPage]]
    page_count: int
    copies: int
    paper: str
    width_mm: float
    height_mm: float
    orientation: str
    dpi: int


@dataclass(frozen=True)
class SpoolResult:
    """Resultado do envio. ``accepted`` NÃO significa papel impresso.

    ``confirmed`` só é verdadeiro quando a saída foi efetivamente produzida e verificada
    (ex.: arquivo PDF gravado e relido). Para impressoras Windows é sempre falso no envio;
    a confirmação, se houver, vem depois por ``job_status``.
    """

    accepted: bool
    spool_job_id: int | None
    error: str | None = None
    confirmed: bool = False
    output_path: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class SpoolStatus:
    state: str          # "queued" | "printing" | "printed" | "error" | "deleted" | "gone" | "unknown"
    detail: str = ""


@runtime_checkable
class PrinterBackend(Protocol):
    name: str
    def list_printers(self) -> list[PrinterInfo]: ...
    def submit(self, request: SpoolRequest) -> SpoolResult: ...
    def job_status(self, printer: str, spool_job_id: int) -> SpoolStatus: ...


# ---------------------------------------------------------------------------
# Licença
# ---------------------------------------------------------------------------
class LicenseState(str, enum.Enum):
    NOT_ACTIVATED = "not_activated"
    VALID = "valid"
    EXPIRED = "expired"
    INVALID = "invalid"
    HARDWARE_MISMATCH = "hardware_mismatch"


@dataclass(frozen=True)
class LicenseStatus:
    state: LicenseState
    installation_id: str
    edition: str | None = None
    features: Sequence[str] = ()
    expires_at: datetime | None = None
    message: str = ""


@runtime_checkable
class LicenseValidator(Protocol):
    def status(self) -> LicenseStatus: ...


# ---------------------------------------------------------------------------
# Eventos
# ---------------------------------------------------------------------------
@runtime_checkable
class EventSink(Protocol):
    def add(self, *, level: str, category: str, action: str, message: str,
            device_id: int | None = None, job_id: int | None = None,
            actor: str | None = None, details: Mapping[str, Any] | None = None) -> int: ...
