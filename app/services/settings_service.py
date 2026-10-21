"""Configurações tipadas, validadas, persistidas e auditadas (§17, §18).

* Toda chave é declarada em ``DEFINITIONS`` com tipo, padrão e validador — não existem
  configurações implícitas.
* ``update()`` valida **todas** as alterações (inclusive regras entre campos) antes de
  gravar; a gravação, o histórico de alterações e o evento de auditoria ocorrem na
  mesma transação.
* Valores armazenados inválidos (ex.: banco editado manualmente) não derrubam a
  aplicação: o padrão é usado e um alerta é registrado.
* Exportação/importação em JSON, sem chaves somente-leitura (ID da instalação).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from app import __version__
from app.core.errors import SettingsValidationError, ValidationError
from app.database.connection import Database
from app.database.repositories.events_repo import Category, EventRepository
from app.database.repositories.settings_repo import ChangeHistoryRepository, SettingsRepository
from app.security import validators as v
from app.utils.logging_setup import get_logger

log = get_logger("settings")

EXPORT_FORMAT = "vyonix-settings"
EXPORT_FORMAT_VERSION = 1


def _custom_paper(value):
    from app.printing.paper import parse_custom
    w, h = parse_custom(value)
    return f"{w:g}x{h:g}"


@dataclass(frozen=True)
class SettingDef:
    key: str
    label: str
    group: str
    kind: str                         # "str" | "int" | "bool" | "choice"
    default: Any
    validator: Callable[[Any], Any] | None = None
    choices: tuple[tuple[str, str], ...] = ()   # (valor, rótulo)
    minimum: int | None = None
    maximum: int | None = None
    help: str = ""
    readonly: bool = False
    restart_required: bool = False
    exportable: bool = True

    def validate(self, value: Any) -> Any:
        if self.kind == "bool":
            if not isinstance(value, bool):
                raise ValidationError(f"{self.label}: valor deve ser verdadeiro ou falso.", self.key)
            return value
        if self.kind == "choice":
            allowed = [c[0] for c in self.choices]
            if value not in allowed:
                raise ValidationError(f"{self.label}: valor deve ser um de {', '.join(allowed)}.",
                                      self.key)
            return value
        if self.validator is None:
            return value
        try:
            return self.validator(value)
        except ValidationError as exc:
            raise ValidationError(str(exc), self.key) from exc


GROUPS: tuple[tuple[str, str], ...] = (
    ("site", "Instalação"),
    ("dicom_storage", "DICOM — Recepção (Storage SCP)"),
    ("dicom_print", "DICOM — Impressão (Print SCP)"),
    ("jobs", "Fila de impressão"),
    ("printing", "Impressão — padrões"),
    ("print_identity", "Identidade da Impressão (cabeçalho e rodapé BMP)"),
    ("retention", "Retenção de dados"),
    ("security", "Segurança"),
    ("ui", "Interface"),
    ("diagnostics", "Diagnóstico"),
)

DEFINITIONS: tuple[SettingDef, ...] = (
    SettingDef("system.installation_id", "ID da instalação", "site", "str", "",
               readonly=True, exportable=False,
               help="Identificador único desta instalação. Usado no licenciamento offline."),
    SettingDef("site.name", "Nome da unidade", "site", "str", "",
               validator=v.free_text(120, "Nome da unidade"),
               help="Exibido no cabeçalho do Dashboard e, futuramente, nas impressões."),

    SettingDef("dicom.storage.ae_title", "AE Title local", "dicom_storage", "str", "VYONIX",
               validator=v.validate_ae_title, restart_required=True,
               help="Até 16 caracteres ASCII. Deve ser informado nos equipamentos."),
    SettingDef("dicom.storage.bind_address", "Endereço IP de escuta", "dicom_storage", "str",
               "0.0.0.0", validator=v.validate_bind_address, restart_required=True,
               help="0.0.0.0 escuta em todas as interfaces IPv4."),
    SettingDef("dicom.storage.port", "Porta TCP", "dicom_storage", "int", 11112,
               validator=v.validate_port, minimum=1, maximum=65535, restart_required=True),
    SettingDef("dicom.storage.max_associations", "Associações simultâneas (máx.)",
               "dicom_storage", "int", 10, validator=v.int_range(1, 64, "Associações simultâneas"),
               minimum=1, maximum=64, restart_required=True),
    SettingDef("dicom.storage.autostart", "Iniciar a recepção automaticamente", "dicom_storage",
               "bool", True, help="Inicia o Storage SCP quando o VYONIX abre."),
    SettingDef("dicom.storage.max_instance_mb", "Tamanho máximo por imagem (MB)", "dicom_storage",
               "int", 1024, validator=v.int_range(1, 4096, "Tamanho máximo por imagem"),
               minimum=1, maximum=4096,
               help="Imagens maiores são recusadas com status 0xA700 (sem recursos)."),
    SettingDef("dicom.storage.accept_unknown", "Aceitar equipamentos não cadastrados",
               "dicom_storage", "bool", False,
               help="Desativado por padrão: somente equipamentos cadastrados e autorizados "
                    "podem enviar imagens."),

    SettingDef("dicom.print.enabled", "Habilitar DICOM Print SCP", "dicom_print", "bool", True,
               help="Recebe filmes de equipamentos que imprimem via DICOM (Basic Print Management). "
                    "Usa o mesmo cadastro e autorização de equipamentos da recepção."),
    SettingDef("dicom.print.color", "Aceitar impressão colorida", "dicom_print", "bool", True,
               help="Oferece a Basic Color Print Management Meta SOP Class além da escala de cinza."),
    SettingDef("dicom.print.policy", "Prioridade do pedido DICOM Print (padrão)", "dicom_print", "choice",
               "device_first",
               choices=(("device_first", "Configuração do equipamento prevalece"),
                        ("dicom_first", "Pedido DICOM Print prevalece"),
                        ("ignore_dicom", "Ignorar parâmetros do pedido")),
               help="Vale para equipamentos sem política própria. Afeta layout, orientação e cópias pedidos "
                    "pelo equipamento via DICOM Print."),
    SettingDef("dicom.print.honor_density", "Aplicar densidades do filme ao papel", "dicom_print", "bool",
               False, help="Desligado: fundo e bordas pretos pedidos para filme não são impressos no papel "
                           "(evita páginas inteiras pretas). Ligado: Empty Image Density BLACK/WHITE é aplicada."),
    SettingDef("dicom.print.ae_title", "AE Title de impressão", "dicom_print", "str",
               "VYONIX_PRINT", validator=v.validate_ae_title, restart_required=True),
    SettingDef("dicom.print.port", "Porta TCP de impressão", "dicom_print", "int", 11113,
               validator=v.validate_port, minimum=1, maximum=65535, restart_required=True),

    SettingDef("jobs.max_attempts", "Tentativas automáticas", "jobs", "int", 3,
               validator=v.int_range(1, 10, "Tentativas automáticas"), minimum=1, maximum=10),
    SettingDef("jobs.retry_delay_seconds", "Intervalo entre tentativas (s)", "jobs", "int", 30,
               validator=v.int_range(5, 3600, "Intervalo entre tentativas"), minimum=5,
               maximum=3600),
    SettingDef("printing.default_printer", "Impressora padrão do VYONIX", "jobs", "str", "",
               validator=v.free_text(256, "Impressora padrão"),
               help="Escolha na página Impressoras (botão “Definir como padrão do VYONIX”). Vazio: "
                    "usa a impressora padrão do Windows."),
    SettingDef("jobs.auto_print", "Imprimir automaticamente o que for recebido", "jobs", "bool", True,
               help="Cada série recebida pelo Storage SCP vira um trabalho de impressão depois do "
                    "intervalo de agrupamento abaixo."),
    SettingDef("jobs.collect_seconds", "Agrupar imagens da série por (s)", "jobs", "int", 15,
               validator=v.int_range(2, 600, "Agrupamento"), minimum=2, maximum=600,
               help="Tempo sem novas imagens da mesma série antes de criar o trabalho."),
    SettingDef("jobs.hold_new", "Reter trabalhos novos para liberação manual", "jobs", "bool", False,
               help="Os trabalhos entram como “Retido” e só imprimem depois de liberados."),

    SettingDef("printing.paper", "Papel", "printing", "choice", "A4",
               choices=(("A4", "A4"), ("A3", "A3"), ("Letter", "Carta"), ("Legal", "Ofício"),
                        ("A5", "A5"), ("Tabloid", "Tabloide"), ("custom", "Personalizado"))),
    SettingDef("printing.custom_paper", "Papel personalizado (mm)", "printing", "str", "210x330",
               validator=lambda x: _custom_paper(x),
               help="Largura x altura em milímetros (50 a 1200), usado quando o papel é “Personalizado”. "
                    "O formato precisa ser aceito pelo driver da impressora."),
    SettingDef("printing.orientation", "Orientação", "printing", "choice", "auto",
               choices=(("auto", "Automática"), ("portrait", "Retrato"), ("landscape", "Paisagem"))),
    SettingDef("printing.layout", "Layout (linhas x colunas)", "printing", "choice", "1x1",
               choices=tuple((x, x.replace("x", " × ")) for x in
                             ("1x1", "1x2", "2x1", "2x2", "2x3", "3x2", "3x3", "4x4"))),
    SettingDef("printing.dpi", "Resolução de saída (dpi)", "printing", "int", 300,
               validator=v.int_range(150, 600, "Resolução de saída"), minimum=150, maximum=600,
               help="Resolução das páginas enviadas à impressora (não altera a imagem médica). "
                    "300 dpi atende a maioria das impressoras com uso moderado de memória."),
    SettingDef("printing.margin_mm", "Margens (mm)", "printing", "int", 10,
               validator=v.int_range(0, 40, "Margens"), minimum=0, maximum=40),
    SettingDef("printing.spacing_mm", "Espaçamento entre imagens (mm)", "printing", "int", 3,
               validator=v.int_range(0, 20, "Espaçamento"), minimum=0, maximum=20),
    SettingDef("printing.copies", "Cópias", "printing", "int", 1,
               validator=v.int_range(1, 99, "Cópias"), minimum=1, maximum=99),
    SettingDef("printing.border", "Borda nas imagens", "printing", "bool", False),
    SettingDef("printing.header_text", "Texto do cabeçalho", "printing", "str", "",
               validator=v.free_text(120, "Cabeçalho"), help="Ex.: nome da clínica."),
    SettingDef("printing.footer_text", "Texto do rodapé", "printing", "str", "",
               validator=v.free_text(120, "Rodapé")),
    SettingDef("printing.exam_info", "Informações do exame no cabeçalho", "printing", "bool", True,
               help="Modalidade, data de recebimento e equipamento (sem dados do paciente)."),
    SettingDef("printing.patient_info", "Nome e ID do paciente no cabeçalho", "printing", "bool",
               False, help="Desativado por padrão (LGPD). Quando ativo, os dados são lidos do arquivo "
                           "DICOM apenas no momento da impressão e não são gravados no banco nem nos logs."),
    SettingDef("printing.page_numbers", "Numerar páginas", "printing", "bool", True),
    SettingDef("printing.min_effective_dpi", "Alertar resolução efetiva abaixo de (dpi)", "printing", "int", 100,
               validator=v.int_range(30, 600, "Resolução mínima"), minimum=30, maximum=600,
               help="Resolução da imagem de origem no tamanho impresso. Abaixo deste valor o trabalho registra "
                    "um alerta (a imagem é ampliada além da sua resolução)."),

    SettingDef("print_identity.header_enabled", "Imprimir cabeçalho BMP (padrão)", "print_identity", "bool",
               False, help="Pode ser ligado ou desligado em cada equipamento."),
    SettingDef("print_identity.footer_enabled", "Imprimir rodapé BMP (padrão)", "print_identity", "bool",
               False, help="Pode ser ligado ou desligado em cada equipamento."),
    SettingDef("print_identity.gap_mm", "Espaço entre cabeçalho/rodapé e imagens (mm)", "print_identity", "int",
               3, validator=v.int_range(0, 30, "Espaço"), minimum=0, maximum=30),
    SettingDef("print_identity.max_height_mm", "Altura máxima do cabeçalho/rodapé (mm, 0 = sem limite)",
               "print_identity", "int", 0, validator=v.int_range(0, 60, "Altura máxima"), minimum=0, maximum=60,
               help="A arte mantém a proporção 3000:206; limitar a altura reduz também a largura."),

    SettingDef("retention.images_days", "Reter imagens recebidas (dias)", "retention", "int", 30,
               validator=v.int_range(1, 3650, "Retenção de imagens"), minimum=1, maximum=3650,
               help="Política de retenção (LGPD): imagens e PDFs gerados mais antigos são removidos "
                    "automaticamente, exceto os ligados a trabalhos não concluídos."),
    SettingDef("retention.events_days", "Reter eventos (dias)", "retention", "int", 365,
               validator=v.int_range(30, 3650, "Retenção de eventos"), minimum=30, maximum=3650),

    SettingDef("security.lock_minutes", "Bloquear administração após (min)", "security", "int", 10,
               validator=v.int_range(1, 240, "Tempo de bloqueio"), minimum=1, maximum=240,
               help="Depois de desbloquear com a senha de administrador, as funções protegidas "
                    "voltam a exigir a senha após este tempo sem uso."),

    SettingDef("ui.theme", "Tema", "ui", "choice", "system",
               choices=(("system", "Seguir o Windows"), ("light", "Claro"), ("dark", "Escuro"))),
    SettingDef("ui.close_to_tray", "Fechar a janela mantém o VYONIX na bandeja", "ui", "bool", True,
               help="O ícone ao lado do relógio mostra o estado dos serviços. Para sair, use “Sair” no menu "
                    "do ícone. Com o serviço Windows ativo, a recepção e a impressão continuam mesmo após sair."),

    SettingDef("logging.level", "Nível de log", "diagnostics", "choice", "INFO",
               choices=tuple((lvl, lvl) for lvl in v.LOG_LEVELS),
               help="Aplicado imediatamente, sem reiniciar."),
)

_BY_KEY: dict[str, SettingDef] = {d.key: d for d in DEFINITIONS}


@dataclass
class UpdateResult:
    changed: dict[str, tuple[Any, Any]] = field(default_factory=dict)   # chave → (antigo, novo)
    warnings: list[str] = field(default_factory=list)
    restart_required: bool = False


class SettingsService:
    def __init__(self, db: Database, events: EventRepository) -> None:
        self.db = db
        self.repo = SettingsRepository(db)
        self.history = ChangeHistoryRepository(db)
        self.events = events
        self._listeners: list[Callable[[Mapping[str, Any]], None]] = []

    # ------------------------------------------------------------------ leitura
    @staticmethod
    def definitions() -> tuple[SettingDef, ...]:
        return DEFINITIONS

    @staticmethod
    def definition(key: str) -> SettingDef:
        try:
            return _BY_KEY[key]
        except KeyError:
            raise KeyError(f"Configuração desconhecida: {key}") from None

    def get(self, key: str) -> Any:
        d = self.definition(key)
        raw = self.repo.get_raw(key)
        if raw is None:
            return d.default
        try:
            return d.validate(raw)
        except ValidationError:
            log.warning("Valor armazenado inválido; usando padrão", extra={"key": key})
            return d.default

    def get_all(self) -> dict[str, Any]:
        stored = self.repo.all_raw()
        result: dict[str, Any] = {}
        for d in DEFINITIONS:
            raw = stored.get(d.key)
            if raw is None:
                result[d.key] = d.default
                continue
            try:
                result[d.key] = d.validate(raw)
            except ValidationError:
                log.warning("Valor armazenado inválido; usando padrão", extra={"key": d.key})
                result[d.key] = d.default
        return result

    # ----------------------------------------------------------------- escrita
    def ensure_defaults(self) -> None:
        """Gera valores que precisam existir desde a primeira execução."""
        if not self.repo.get_raw("system.installation_id"):
            with self.db.transaction():
                self.repo.upsert("system.installation_id", str(uuid.uuid4()).upper(), "system")
            self.events.add(level="INFO", category=Category.SYSTEM, action="installation.created",
                            message="Nova instalação inicializada.", actor="system")

    def validate(self, changes: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        """Valida sem gravar. Retorna (valores normalizados, erros por chave)."""
        clean: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for key, value in changes.items():
            d = _BY_KEY.get(key)
            if d is None:
                errors[key] = "Configuração desconhecida."
                continue
            if d.readonly:
                errors[key] = "Configuração somente leitura."
                continue
            try:
                clean[key] = d.validate(value)
            except ValidationError as exc:
                errors[key] = str(exc)
        if not errors:
            merged = {**self.get_all(), **clean}
            errors.update(self._cross_validate(merged))
        return clean, errors

    def update(self, changes: Mapping[str, Any], *, actor: str,
               reason: str | None = None) -> UpdateResult:
        clean, errors = self.validate(changes)
        if errors:
            raise SettingsValidationError(errors)

        current = self.get_all()
        result = UpdateResult()
        diff = {k: (current[k], val) for k, val in clean.items() if current[k] != val}
        if not diff:
            return result

        with self.db.transaction():
            for key, (old, new) in diff.items():
                self.repo.upsert(key, new, actor)
                self.history.record(entity_type="settings", entity_id=key, field="value",
                                    old_value=old, new_value=new, actor=actor, reason=reason)
            self.events.add(
                level="INFO", category=Category.ADMIN, action="settings.update",
                message=f"{len(diff)} configuração(ões) alterada(s).", actor=actor,
                details={"changes": {k: {"old": o, "new": n} for k, (o, n) in diff.items()},
                         "reason": reason},
            )

        result.changed = diff
        result.restart_required = any(_BY_KEY[k].restart_required for k in diff)
        merged = {**current, **clean}
        result.warnings = self._warnings(merged)
        log.info("Configurações alteradas", extra={"keys": sorted(diff), "actor": actor})
        self._notify({k: n for k, (_, n) in diff.items()})
        return result

    def reset_to_defaults(self, keys: list[str] | None = None, *, actor: str) -> UpdateResult:
        targets = keys or [d.key for d in DEFINITIONS if not d.readonly]
        return self.update({k: self.definition(k).default for k in targets}, actor=actor,
                           reason="Restaurar padrões")

    # ------------------------------------------------------- exportar/importar
    def export_json(self, path: Path) -> Path:
        values = {d.key: val for d, val in ((d, self.get(d.key)) for d in DEFINITIONS)
                  if d.exportable}
        payload = {"format": EXPORT_FORMAT, "format_version": EXPORT_FORMAT_VERSION,
                   "app_version": __version__, "settings": values}
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        self.events.add(level="INFO", category=Category.ADMIN, action="settings.export",
                        message="Configurações exportadas.", actor="system",
                        details={"file": path.name})
        return path

    def import_json(self, path: Path, *, actor: str) -> UpdateResult:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SettingsValidationError({"arquivo": f"Não foi possível ler o arquivo: {exc}"})
        if not isinstance(payload, dict) or payload.get("format") != EXPORT_FORMAT:
            raise SettingsValidationError({"arquivo": "Arquivo não é uma exportação do VYONIX."})
        if payload.get("format_version") != EXPORT_FORMAT_VERSION:
            raise SettingsValidationError({"arquivo": "Versão de formato não suportada."})
        settings = payload.get("settings")
        if not isinstance(settings, dict):
            raise SettingsValidationError({"arquivo": "Seção 'settings' ausente."})
        importable = {k: val for k, val in settings.items()
                      if not (k in _BY_KEY and not _BY_KEY[k].exportable)}
        return self.update(importable, actor=actor, reason=f"Importação de {path.name}")

    # ------------------------------------------------------------- ouvintes
    def subscribe(self, listener: Callable[[Mapping[str, Any]], None]) -> None:
        self._listeners.append(listener)

    def _notify(self, changed: Mapping[str, Any]) -> None:
        for listener in list(self._listeners):
            try:
                listener(changed)
            except Exception:  # um ouvinte com defeito não pode impedir a gravação
                log.exception("Falha em ouvinte de configurações")

    # ------------------------------------------------------------- regras
    @staticmethod
    def _cross_validate(values: Mapping[str, Any]) -> dict[str, str]:
        errors: dict[str, str] = {}
        # O Print SCP escuta no mesmo endereço do Storage SCP; as portas devem diferir.
        if values["dicom.print.enabled"] and \
                values["dicom.storage.port"] == values["dicom.print.port"]:
            errors["dicom.print.port"] = "A porta de impressão deve ser diferente da porta de recepção."
        if values["dicom.print.enabled"] and \
                values["dicom.storage.ae_title"] == values["dicom.print.ae_title"]:
            errors["dicom.print.ae_title"] = (
                "Use AE Titles distintos para recepção e impressão, para que os equipamentos "
                "possam endereçar cada serviço.")
        return errors

    @staticmethod
    def _warnings(values: Mapping[str, Any]) -> list[str]:
        warnings = list(v.port_warnings(values["dicom.storage.port"]))
        if values["dicom.print.enabled"]:
            warnings += v.port_warnings(values["dicom.print.port"])
        if values["dicom.storage.accept_unknown"]:
            warnings.append("Equipamentos não cadastrados poderão enviar imagens. "
                            "Recomendado apenas durante a implantação.")
        return sorted(set(warnings))

    def current_warnings(self) -> list[str]:
        return self._warnings(self.get_all())
