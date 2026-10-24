"""Erros de domínio do CORE (convertidos em respostas HTTP pela API)."""


class VyonixError(Exception):
    status = 400
    code = "invalid"

    def __init__(self, message: str, *, code: str | None = None, details: dict | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code
        self.details = details or {}


class ValidationFailed(VyonixError):
    status, code = 422, "validation"


class NotFound(VyonixError):
    status, code = 404, "not_found"


class Conflict(VyonixError):
    status, code = 409, "conflict"


class Unauthorized(VyonixError):
    status, code = 401, "unauthorized"


class Forbidden(VyonixError):
    status, code = 403, "forbidden"


class NotLicensed(VyonixError):
    """Módulo sem direito vigente — distinto de falta de permissão do usuário."""
    status, code = 402, "not_licensed"


class Locked(VyonixError):
    status, code = 423, "locked"


class Unavailable(VyonixError):
    """Dependência externa (ex.: motor de armazenamento DICOM) não configurada ou sem resposta."""
    status, code = 503, "unavailable"
