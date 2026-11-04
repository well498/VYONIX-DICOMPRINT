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

## Apresentação 2 — 04/11/2026 (protótipos reformulados, prompt mestre dos três perfis)
Canvas "Protótipos VYONIX — Técnico, Radiologista e Paciente" (https://claude.ai/artifact/5WGSnzQ4JYijgwhy3qh32q).
Classificação de todos os quadros: **PROTÓTIPO** (dados fictícios; nada implementado; nada testado no computador do proprietário).
| Quadro | Perfil | Tela |
|---|---|---|
| 1 | Técnico | Exames recebidos |
| 1b | Técnico | Exames recebidos v2 — ideias das fotos de referência, lote 1 (`Referencias_Fotos_Lote1.md`) |
| 2 | Técnico | Conferência técnica com Prioridade e Trocar médico |
| 3 | Radiologista | Fila de exames (prazo restante, filtros) |
| 4 | Radiologista | Ambiente de laudo (Fila/Imagens/Laudo, 2º monitor, rascunho automático, Salvar/Revisar/Assinar, BLK-14) |
| 5 | Radiologista | Preferências do visualizador (Automático/Weasis/Outro/Viewer Web; conector local com confirmação) |
| 6 | Paciente | Início ("Olá, Ana Paula!") |
| 7 | Paciente | Meus exames (estados em linguagem simples) |
| 8 | Paciente | Resultado: Laudo / Imagens / Detalhes; compartilhamento temporário |
| 9 | Paciente | Celular 390×844 com navegação inferior |
| 10 | Recepção | Agenda do dia com check-in no painel lateral, pendências não impeditivas na urgência |
| 12 / 12b | Administrador da clínica | Visão geral sem dados clínicos; Prazos de laudo configuráveis (sem efeito retroativo por padrão) |
| 11 | Coordenação do CDI (opcional) | Painel operacional, urgentes por prazo, aprovações (desconsiderar, prioridade, trocar médico), distribuição |

| Quadro | Avaliação do proprietário | Ajustes aprovados → backlog |
|---|---|---|
| 1–9, 1b | D-06..D-09 aprovadas em 04/11 02:36 (ver Referencias_Fotos_Lote1.md §5b) | REF-02, REF-05, REF-06 com regras de aprovação |
| 10, 11 | ajustes de 04/11 02:42 aplicados; 11 v2 sem aprovação de prioridade/troca (regra 02:59) | aguardando aprovação do desenho |
| 1b (bloqueio), 12, 12b | aguardando | — |
