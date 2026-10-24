"""Interface do motor de armazenamento DICOM (ADR-0012).

O módulo PACS conversa com o motor só por esta interface. O motor de produção é o Orthanc
(``vyonix.pacs.orthanc``), sem modificações e sem plugins AGPL. A autorização, o isolamento por
organização, o índice consultado pelo DICOMweb e a auditoria ficam no CORE — o motor não é
multiorganização e nunca é exposto diretamente.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class StoredRef:
    """Onde o motor guardou a instância (identificador interno dele) e o que ele confirmou."""
    backend_id: str
    sop_uid: str
    already_existed: bool = False


@dataclass(frozen=True)
class Change:
    """Instância nova recebida diretamente pelo motor (C-STORE de uma modalidade)."""
    seq: int
    backend_id: str


class PacsBackend(Protocol):
    name: str

    def ping(self) -> dict:
        """Versão e estado do motor; levanta ``BackendUnavailable`` se ele não responder."""

    def store(self, data: bytes) -> StoredRef:
        """Guarda um arquivo DICOM Part 10 sem alterá-lo."""

    def fetch(self, backend_id: str) -> bytes:
        """Devolve o arquivo DICOM exatamente como foi guardado."""

    def changes(self, since: int, limit: int = 100) -> tuple[list[Change], int, bool]:
        """Instâncias novas depois de ``since``: (mudanças, último seq, terminou)."""

    def origin(self, backend_id: str) -> dict:
        """Como a instância chegou: ``origin`` (DicomProtocol, RestApi…), ``called_aet``, ``remote_aet``, ``remote_ip``."""

    def delete(self, backend_id: str) -> None:
        """Remove uma instância (usado só para desfazer uma entrada recusada pelo índice)."""


class BackendUnavailable(RuntimeError):
    """O motor de armazenamento não respondeu."""
