"""Filtro SQL por unidade (P0 0.3.2), sem dependência de autenticação — usado pelos serviços de domínio."""
from __future__ import annotations

import uuid

from sqlalchemy import true

SENTINEL = uuid.UUID(int=0)          # nunca é unidade real: lista vazia de unidades permitidas → nada passa


def where_site(col, allowed: set | None):
    """``allowed`` None = todas as unidades; senão só essas — ``NULL`` (sem unidade) nunca passa."""
    if allowed is None:
        return true()
    return col.in_(list(allowed) or [SENTINEL])
