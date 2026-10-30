# Registro de telas apresentadas ao proprietário (diretriz de 29/10/2026 22:08)

Diretriz permanente: apresentar progressivamente as telas prontas (captura real quando implementada; protótipo
quando não), com módulo, perfil, funções, melhorias, pendências e limitações; classificar IMPLEMENTADA / PROTÓTIPO /
EM DESENVOLVIMENTO / VALIDADA; comparar antes × depois; registrar avaliação e ajustes aprovados no backlog; não
reapresentar sem mudança relevante; não afirmar teste no computador do proprietário.

**Página de revisão:** artifact "Revisão das Telas VYONIX" (https://claude.ai/artifact/VADAVXQE59fQ4xqjHb8YTR).
As avaliações do proprietário ficam no banco da própria página (coleção `avaliacoes`, só o proprietário grava) e
são lidas pelo coordenador para o backlog.

## Apresentação 1 — 29/10/2026 22:30 (telas atuais, antes da reformulação)
Capturas reais: web compilada do ramo develop, servidor e PostgreSQL reais, Chromium, dados fictícios; 13 testes
ponta a ponta aprovados localmente (22:09). Classificação: VALIDADA (testes automáticos locais); nenhuma testada no
computador do proprietário.
| Perfil | Telas |
|---|---|
| Técnico | Painel do técnico; ficha do estudo; preparação e encaminhamento; ficha no celular; estudo encaminhado |
| Médico | Fila de laudos; editor; assinatura e laudo liberado; Abrir imagens; Minha produção |
| Recepção | Pacientes; Agenda; ficha e cadastro duplicado |
| Coordenador | Central de exames; Médicos e vínculos |
| Administrador | Usuários e papéis; identidade dos laudos; equipamentos (Nós DICOM); imagens e protocolos; auditoria; licença; início |
| Central/Telelaudos | Central de exames; fila de laudos (mesmas telas) |
| Solicitante / Paciente | Não existem (INT-07, BLK-06) |
| Admin global | Nova instituição; instituições |

Correção feita durante a preparação e mostrada como antes × depois: **UX-A-026** — botão "Excluir imagem" da
assinatura invisível (texto vermelho sobre fundo vermelho), commit `76c6754`.

| Tela | Avaliação do proprietário | Ajustes aprovados → backlog |
|---|---|---|
| (todas) | aguardando | — |
