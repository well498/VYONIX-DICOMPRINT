"""Falhas simuladas para os testes de homologação (CI Windows).

Ativadas **somente** pela variável de ambiente ``VYONIX_DEPLOY_FALHA_SIMULADA`` (lista separada por vírgulas), que
nenhum serviço, atalho ou instalador do VYONIX define. Servem para provar, no Windows real, que uma falha durante a
migração do banco ou na inicialização depois de uma atualização interrompe a operação com segurança, fica registrada
e não perde dados.

* ``migracao``: a etapa do banco (migrações) falha antes de alterar o banco.
* ``inicializacao``: o VYONIX Core não é confirmado em funcionamento depois de iniciado.
"""

from __future__ import annotations

import os

VAR = "VYONIX_DEPLOY_FALHA_SIMULADA"


def active(name: str) -> bool:
    return name in {x.strip() for x in os.environ.get(VAR, "").split(",") if x.strip()}
