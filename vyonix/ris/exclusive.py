"""Exclusividade do Técnico em Radiologia (regra definitiva do proprietário, 04/11/2026).

Somente quem tem o papel ``tecnico`` (Técnico em Radiologia) atribuído — na unidade do exame ou em todas — pode:

* trocar o médico responsável pelo exame;
* alterar a prioridade (Rotina / Prioritário / Urgente);

e apenas antes do início efetivo da elaboração do laudo (``vyonix.report.lock``). Permissões acumuladas de outros
papéis (administrador ``*``, coordenação, gestor de telelaudos, supervisor, médico) **não** concedem essas ações,
nem permitem autorizá-las para outro perfil. A verificação é feita no backend, em todas as rotas que alteram
médico ou prioridade.
"""
from __future__ import annotations

import uuid

from vyonix.errors import Forbidden

ROLE = "tecnico"
MESSAGE = "Somente o Técnico em Radiologia pode trocar o médico ou alterar a prioridade do exame."


def is_technician(principal, site_id: uuid.UUID | None = None) -> bool:
    if getattr(principal, "stage", "ok") != "ok":
        return False
    for r in getattr(principal, "roles", None) or []:
        if r.get("role") != ROLE:
            continue
        sid = r.get("site_id")
        if sid is None or site_id is None or str(sid) == str(site_id):
            return True
    return False


def require(principal, site_id: uuid.UUID | None, *, action: str) -> None:
    if not is_technician(principal, site_id):
        raise Forbidden(MESSAGE, code="technician_only", details={"action": action})
