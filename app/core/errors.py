"""Hierarquia de exceções do VYONIX."""

from __future__ import annotations


class VyonixError(Exception):
    """Base de todas as exceções da aplicação."""


class ConfigurationError(VyonixError):
    """Configuração inválida ou inconsistente."""


class ValidationError(VyonixError):
    """Valor de entrada inválido. ``field`` identifica o campo, quando aplicável."""

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


class SettingsValidationError(VyonixError):
    """Um ou mais valores de configuração são inválidos."""

    def __init__(self, errors: dict[str, str]) -> None:
        self.errors = dict(errors)
        detail = "; ".join(f"{k}: {v}" for k, v in self.errors.items())
        super().__init__(f"Configuração inválida — {detail}")


class DatabaseError(VyonixError):
    """Falha de banco de dados."""


class MigrationError(DatabaseError):
    """Falha ao aplicar ou validar migrações."""


class DatabaseIntegrityError(DatabaseError):
    """O arquivo do banco está corrompido."""


class InvalidStateTransition(VyonixError):
    """Transição de estado de trabalho não permitida."""
