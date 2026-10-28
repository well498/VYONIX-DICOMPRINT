"""Importa todos os modelos (metadados completos para as migrações)."""

from vyonix.audit.models import AuditEntry  # noqa: F401
from vyonix.auth.models import AuthSession, MfaFactor, Permission, Role, RolePermission, User, UserRole  # noqa: F401
from vyonix.clinical.models import (Encounter, Order, Patient, PatientIdentifier, PatientMerge,  # noqa: F401
                                    Procedure, Study)
from vyonix.events.models import InboxEntry, OutboxEvent  # noqa: F401
from vyonix.licensing.models import Entitlement, LicenseDocument  # noqa: F401
from vyonix.modules.models import ModuleState  # noqa: F401
from vyonix.pacs.models import (PacsAeRoute, PacsCloudSyncState, PacsDicomNode, PacsInstance, PacsSeries,  # noqa: F401
                                PacsStudy, PacsSyncState)
from vyonix.settings.models import Setting, SettingHistory  # noqa: F401
from vyonix.tenancy.models import Installation, Organization, Site  # noqa: F401
from vyonix.ris.models import Room, Schedule  # noqa: F401
from vyonix.report.models import (Assignment, Asset, BrandingVersion, CriticalAlert, Physician,  # noqa: F401
                                  PhysicianLink, Report, ReportTemplate, ReportVersion, SignatureImage,
                                  TemplateVersion)
