"""Variante da compilação. No repositório é SEMPRE ``commercial`` (conferido pelo teste de arquitetura).

O pipeline de homologação interna (``deploy-windows`` disparado manualmente com ``flavor=homologacao``) troca este
arquivo **só na cópia de compilação** para gerar o instalador "VYONIX Homologação": módulos liberados sem licença
comercial, faixa "HOMOLOGAÇÃO INTERNA — SEM LICENÇA" em todas as telas e nada de uso com pacientes. Não há como ligar
esta variante por configuração ou variável de ambiente numa instalação comercial.
"""

FLAVOR = "commercial"
HOMOLOG = FLAVOR == "homologacao"
