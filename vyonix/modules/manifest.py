"""Manifestos dos módulos da plataforma.

Cada módulo declara código, versão, dependências, permissões, configurações (com esquema), eventos
publicados/consumidos e se exige licença. ``available=False`` = módulo planejado: aparece no
catálogo, mas não pode ser habilitado até ser entregue (nada de módulos de fachada).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class SettingSpec:
    key: str
    model: type[BaseModel]
    description: str
    scope: str = "tenant"          # tenant | site


@dataclass(frozen=True)
class ModuleManifest:
    code: str
    name: str
    version: str
    description: str
    depends: tuple[str, ...] = ()
    permissions: dict[str, str] = field(default_factory=dict)
    settings: tuple[SettingSpec, ...] = ()
    publishes: tuple[str, ...] = ()
    consumes: tuple[str, ...] = ()
    requires_license: bool = True
    available: bool = True
    always_enabled: bool = False

    def setting(self, key: str) -> SettingSpec | None:
        return next((s for s in self.settings if s.key == key), None)

    def public(self) -> dict[str, Any]:
        return {"code": self.code, "name": self.name, "version": self.version, "description": self.description,
                "depends": list(self.depends), "requires_license": self.requires_license,
                "available": self.available, "always_enabled": self.always_enabled,
                "permissions": sorted(self.permissions), "publishes": list(self.publishes),
                "consumes": list(self.consumes), "settings": [s.key for s in self.settings]}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SecurityPolicy(_Strict):
    session_minutes: int = Field(30, ge=5, le=720, description="Sessão sem uso expira após (minutos)")
    lockout_attempts: int = Field(5, ge=3, le=20, description="Tentativas erradas até bloquear o usuário")
    lockout_minutes: int = Field(15, ge=1, le=1440, description="Tempo de bloqueio (minutos)")
    mfa_required_for_admins: bool = Field(False, description="Exigir verificação em duas etapas dos administradores")
    password_min_length: int = Field(10, ge=10, le=128, description="Tamanho mínimo da senha")


class InstitutionInfo(_Strict):
    display_name: str = Field("", max_length=200, description="Nome exibido")
    document: str = Field("", max_length=20, description="CNPJ")
    phone: str = Field("", max_length=40, description="Telefone")
    email: str = Field("", max_length=200, description="E-mail")
    address: str = Field("", max_length=300, description="Endereço")


class ClinicalPolicy(_Strict):
    accession_prefix: str = Field("", max_length=8, pattern=r"^[A-Z0-9]*$", description="Prefixo do número de acesso")
    require_identifier_issuer: str = Field("", max_length=60, description="Emissor obrigatório no cadastro")
    auto_reconcile_by_accession: bool = Field(True, description="Conciliar estudos automaticamente pelo número de acesso")


class PacsRetention(_Strict):
    years: int = Field(20, ge=5, le=100, description="Prazo mínimo de guarda dos estudos (anos) — confirmar com o "
                                                     "jurídico da clínica")


VERSION = "0.1.0"

CORE = ModuleManifest(
    code="core", name="VYONIX Core", version=VERSION, always_enabled=True,
    description="Organizações, unidades, usuários, permissões, auditoria, configurações, eventos e licenças.",
    permissions={
        "core.users.read": "Consultar usuários", "core.users.manage": "Criar e alterar usuários e papéis",
        "core.settings.read": "Consultar configurações", "core.settings.manage": "Alterar configurações",
        "core.audit.read": "Consultar auditoria", "core.license.read": "Consultar licença",
        "core.license.manage": "Aplicar licenças e solicitar demonstração",
        "core.modules.manage": "Habilitar e desabilitar módulos", "core.sites.manage": "Gerenciar unidades",
    },
    settings=(SettingSpec("security", SecurityPolicy, "Política de acesso"),
              SettingSpec("institution", InstitutionInfo, "Dados da instituição")),
    publishes=("core.user.created.v1", "core.module.enabled.v1", "core.module.disabled.v1",
               "core.license.applied.v1", "core.setting.changed.v1"),
)

CLINICAL = ModuleManifest(
    code="clinical", name="Cadastro clínico", version=VERSION, always_enabled=True, requires_license=False,
    depends=("core",),
    description="Pacientes, identificadores, atendimentos, pedidos, procedimentos e estudos (modelo comum).",
    permissions={
        "clinical.patients.read": "Consultar pacientes", "clinical.patients.write": "Cadastrar e alterar pacientes",
        "clinical.patients.merge": "Mesclar e desfazer mescla de pacientes",
        "clinical.orders.read": "Consultar pedidos", "clinical.orders.write": "Criar e alterar pedidos",
        "clinical.studies.read": "Consultar estudos", "clinical.studies.reconcile": "Conciliar estudos",
        "clinical.procedures.manage": "Gerenciar procedimentos",
    },
    settings=(SettingSpec("policy", ClinicalPolicy, "Regras de cadastro e conciliação"),),
    publishes=("clinical.patient.created.v1", "clinical.patient.updated.v1", "clinical.patient.merged.v1",
               "clinical.patient.unmerged.v1", "clinical.order.created.v1", "clinical.order.updated.v1",
               "clinical.study.registered.v1", "clinical.study.reconciled.v1"),
    consumes=("clinical.order.created.v1", "clinical.study.registered.v1"),
)

PRINT = ModuleManifest(
    code="print", name="VYONIX PRINT", version="1.0.0", depends=("core",),
    description="Impressão DICOM (aplicativo VYONIX DICOM Print já entregue; integração ao Core na Fase 3).",
    permissions={"print.jobs.read": "Consultar impressões", "print.jobs.manage": "Gerenciar impressões",
                 "print.rules.manage": "Gerenciar regras e impressoras"},
)

PACS = ModuleManifest(
    code="pacs", name="VYONIX PACS", version="0.1.0", depends=("core",),
    description="Recepção, armazenamento, indexação, pesquisa e recuperação DICOM (DICOMweb STOW/QIDO/WADO-RS) "
                "sobre o Orthanc sem modificações (ADR-0012). Primeira entrega vertical — não liberada para uso clínico.",
    permissions={"pacs.studies.read": "Pesquisar e abrir estudos de imagem",
                 "pacs.studies.store": "Enviar estudos de imagem (STOW-RS)",
                 "pacs.admin": "Sincronizar e consultar o estado do armazenamento DICOM"},
    settings=(SettingSpec("retention", PacsRetention, "Retenção de estudos (relatório; nada é excluído)"),),
    publishes=("pacs.study.received.v1",),
)

RIS = ModuleManifest(
    code="ris", name="VYONIX RIS", version="0.1.0", depends=("core",),
    description="Agendamento de exames e Modality Worklist (primeira entrega do RIS; agenda completa, recepção e "
                "fluxo de exames ainda planejados). Não liberado para uso clínico.",
    permissions={"ris.schedule.read": "Consultar agendamentos e worklist",
                 "ris.schedule.manage": "Agendar, alterar e cancelar exames",
                 "ris.exam.perform": "Registrar chegada, início e conclusão do exame (técnico)",
                 "ris.rooms.manage": "Cadastrar salas de exame"},
    publishes=("ris.schedule.created.v1",), consumes=("pacs.study.received.v1",),
)

REPORT = ModuleManifest(
    code="report", name="VYONIX REPORT", version="0.1.0", depends=("core",),
    description="Laudos e telelaudo multicliente: médicos e vínculos por unidade, identidade visual por organização e "
                "unidade, modelos versionados com seleção automática e importação DOCX, fila com prazos, liberação com "
                "confirmação de senha (não é assinatura digital ICP-Brasil), versões imutáveis, adendos, PDF, FHIR, "
                "HL7 e DICOM. Não liberado para uso clínico.",
    permissions={"report.read": "Consultar laudos", "report.write": "Redigir laudos (rascunho)",
                 "report.sign": "Liberar laudos e registrar adendos", "report.templates.manage": "Gerenciar modelos",
                 "report.physicians.manage": "Cadastrar médicos e vínculos com unidades",
                 "report.branding.manage": "Configurar a identidade visual dos laudos",
                 "report.assign": "Distribuir exames na fila de laudos (vê todas as unidades)"},
    publishes=("report.finalized.v1", "report.amended.v1", "report.critical.v1"),
)

_PLANNED = [
    ("edge", "VYONIX EDGE", "Agente local: descoberta, sincronização e operação offline."),
    ("cloud", "VYONIX CLOUD", "Ambiente central multi-clínica."),
    ("viewer", "VYONIX VIEWER", "Visualização web de imagens."),
    ("patient", "VYONIX PATIENT", "Portal do paciente."),
    ("notify", "VYONIX NOTIFY", "Mensagens e avisos."),
    ("flow", "VYONIX FLOW", "Regras e automações."),
    ("connect", "VYONIX CONNECT", "Integração HL7/FHIR."),
    ("deploy", "VYONIX DEPLOY", "Instalador inteligente, diagnóstico e reparo."),
]
PLANNED = [ModuleManifest(code=c, name=n, version="planejado", description=d, depends=("core",), available=False)
           for c, n, d in _PLANNED]

# Modelos de perfil **opcionais** (Prompt Mestre §8): só viram papéis quando o administrador da instituição os ativa,
# e depois podem ser personalizados. Os papéis padrão acima continuam criados em toda organização.
ROLE_TEMPLATES: dict[str, tuple[str, list[str], str]] = {
    "coordenador_cdi": ("Coordenador do CDI", ["clinical.*", "ris.*", "pacs.studies.read", "pacs.studies.store",
                                               "report.read", "report.assign", "print.jobs.read", "core.users.read"],
                        "Coordena agenda, exames, conciliação e a distribuição de laudos; não libera laudos"),
    "gestor_telelaudos": ("Gestor de Telelaudos", ["report.read", "report.assign", "report.templates.manage",
                                                   "report.physicians.manage", "report.branding.manage",
                                                   "clinical.studies.read", "pacs.studies.read"],
                          "Distribui exames, cadastra médicos e modelos; não libera laudos"),
    "financeiro": ("Administrador Financeiro", ["core.license.read", "ris.schedule.read"],
                   "Contratos e licença da instituição; sem acesso a imagens e laudos"),
    "suporte_tecnico": ("Técnico de Suporte", ["core.settings.read", "core.audit.read", "core.license.read",
                                               "pacs.admin", "print.jobs.read"],
                        "Diagnóstico do sistema e da integração DICOM; sem acesso a laudos"),
}
STRUCTURES: dict[str, tuple[str, list[str]]] = {
    "clinica_pequena": ("Clínica pequena", []),
    "cdi": ("Centro de diagnóstico (CDI)", ["coordenador_cdi"]),
    "hospital": ("Hospital", ["coordenador_cdi", "gestor_telelaudos", "financeiro", "suporte_tecnico"]),
}

MANIFESTS: dict[str, ModuleManifest] = {m.code: m for m in [CORE, CLINICAL, PRINT, PACS, RIS, REPORT, *PLANNED]}
LICENSABLE = tuple(m.code for m in MANIFESTS.values() if m.requires_license)


def all_permissions() -> dict[str, tuple[str, str]]:
    return {p: (m.code, d) for m in MANIFESTS.values() for p, d in m.permissions.items()}


DEFAULT_ROLES: dict[str, tuple[str, list[str]]] = {
    "administrador": ("Administrador", ["*"]),
    "supervisor": ("Supervisor", ["core.users.read", "core.settings.read", "core.audit.read", "core.license.read",
                                  "clinical.*", "print.*", "pacs.*", "ris.*", "report.read", "report.assign"]),
    "medico": ("Médico", ["core.license.read", "clinical.patients.read", "clinical.orders.read",
                          "clinical.studies.read", "pacs.studies.read", "ris.schedule.read", "report.read",
                          "report.write", "report.sign", "report.templates.manage"]),     # sem cadastro de médicos
    "tecnico": ("Técnico", ["core.license.read", "clinical.patients.read", "clinical.orders.read",
                            "clinical.studies.read", "clinical.studies.reconcile", "print.jobs.read",
                            "print.jobs.manage", "pacs.studies.read", "pacs.studies.store", "ris.schedule.read",
                            "ris.exam.perform"]),
    "recepcionista": ("Recepcionista", ["clinical.patients.read", "clinical.patients.write", "clinical.orders.read",
                                        "clinical.orders.write", "clinical.studies.read", "ris.schedule.read",
                                        "ris.schedule.manage"]),
}
