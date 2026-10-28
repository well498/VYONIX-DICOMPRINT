"""VYONIX REPORT — primeira entrega: laudos de estudos de imagem com modelos, rascunho e liberação.

* Um laudo por estudo (``clinical.studies``). Rascunho editável; **liberação** exige a senha do médico (confirmação
  de identidade no ato) e grava uma versão imutável com SHA-256 do conteúdo. Depois de liberado, o texto não muda:
  correções são **adendos**, também liberados com senha e versionados.
* Achado crítico marcado no laudo gera o evento ``report.critical.v1`` (aviso ao solicitante fica para o NOTIFY).
* **Não é assinatura digital ICP-Brasil** (pendente de decisão do proprietário: certificado, padrão e carimbo de
  tempo). Não liberado para uso clínico.
"""
