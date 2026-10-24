"""VYONIX PACS — recepção, índice, pesquisa e recuperação de estudos DICOM (Entrega 3, ADR-0012).

Motor de armazenamento: Orthanc (processo separado, REST/DICOM, sem plugins AGPL). Índice,
autorização, isolamento por organização, DICOMweb e auditoria: CORE.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vyonix.context import Platform
    from vyonix.pacs.backend import PacsBackend


def backend_for(plat: "Platform") -> "PacsBackend | None":
    """Motor configurado: ``options['pacs_backend']`` (injeção) ou ``pacs_orthanc_url`` na configuração.

    A senha do usuário REST do Orthanc fica no cofre local (``pacs_orthanc_password``), nunca no
    ``config.json``. Sem motor configurado o PACS responde 503 ("armazenamento não configurado").
    """
    b = plat.options.get("pacs_backend")
    if b is not None:
        return b
    url = plat.cfg.extra.get("pacs_orthanc_url")
    if not url:
        return None
    from vyonix.pacs.orthanc import OrthancBackend
    from vyonix.secrets import SecretStore
    user = plat.cfg.extra.get("pacs_orthanc_username")
    pw = SecretStore(plat.cfg.data_dir).get("pacs_orthanc_password") if user else None
    b = OrthancBackend(url, username=user, password=pw.decode() if pw else None)
    plat.options["pacs_backend"] = b
    return b
