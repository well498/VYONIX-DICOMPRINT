# Referências visuais — Lote 1 (04/11/2026)

Registro acumulativo das fotografias de referência enviadas pelo proprietário. As fotografias **não** são versionadas no repositório e nenhum dado identificável que apareça nelas é transcrito aqui (LGPD): várias fotos do sistema de terceiros mostram nomes, registro e data de nascimento de pacientes reais.

Classes: **CONFIRMADO** (visto funcionando nas fotos) · **CONCEITO DO PROPRIETÁRIO** (maquete VYONIX gerada como referência, não é sistema real) · **PROPOSTA VYONIX**.

## 1. Inventário do lote

| # | Imagem | Origem | Perfil | Classe |
|---|---|---|---|---|
| F01 | "1 · Recepção e atendimento": Agenda de exames | Maquete VYONIX | Recepção | CONCEITO DO PROPRIETÁRIO |
| F02 | Técnico: Exames recebidos no PACS + painel de conferência | Maquete VYONIX | Técnico | CONCEITO DO PROPRIETÁRIO |
| F03–F15 | Lista de exames de um PACS em nuvem comercial (foto de tela em uso) | Sistema de terceiros | Técnico / Coordenação / Médico | CONFIRMADO |
| F16 | "6 · Administrador global VYONIX" | Maquete VYONIX | Administrador global | CONCEITO DO PROPRIETÁRIO |
| F17 | "3 · Administrador da clínica" | Maquete VYONIX | Administrador da instituição | CONCEITO DO PROPRIETÁRIO |
| F18 | "5 · Suporte técnico e engenharia" | Maquete VYONIX | Suporte | CONCEITO DO PROPRIETÁRIO |
| F19 | "2 · Coordenador do CDI" | Maquete VYONIX | Coordenação | CONCEITO DO PROPRIETÁRIO |
| F20 | "4 · Médico solicitante" | Maquete VYONIX | Médico solicitante | CONCEITO DO PROPRIETÁRIO |

As maquetes numeradas indicam **sete perfis**: Recepção (1), Coordenador do CDI (2), Administrador da clínica (3), Médico solicitante (4), Suporte (5), Administrador global (6), além do Técnico, do Radiologista e do Paciente já em andamento.

## 2. Sistema de terceiros (F03–F15): o que foi observado

| Ref. | Observação | Avaliação |
|---|---|---|
| R-01 | Linha com ~9 botões redondos só com ícone: visualizadores, anexos, comentários, prioridade, compartilhar, laudo, mais, instituição, médico/relógio | Muita coisa por linha; o significado depende de passar o mouse (não funciona em toque nem para leitor de tela). **Não adotar.** |
| R-02 | Botão de visualizadores abre a escolha entre três visualizadores (impressão, MPR, beta) | Boa ideia: escolher o visualizador no próprio botão. **Adotar** como botão dividido "Abrir imagens ▾". |
| R-03 | Prioridade com menu Rotina/Urgência; **travada quando o laudo está em andamento**, com o motivo no aviso | Regra valiosa. **Adotar** e mostrar o motivo por escrito, não só no aviso. |
| R-04 | Menu do laudo: Achado crítico, Atribuir, Confirmar, Pendenciar; estado "Aguardando laudo"/"Aguardando confirmação" | Confirma o fluxo de conferência → distribuição → laudo. "Pendenciar" = nosso registro de pendência. |
| R-05 | Compartilhar: link e manual/orientações do paciente | Compartilhamento a partir da lista; no VYONIX só com link temporário, prazo, revogação e auditoria (portal, BLK-06). |
| R-06 | Botão (i) do paciente abre registro (com copiar), RG, CPF, sexo, idade, nascimento | **Adotar** com CPF mascarado e dados somente leitura. |
| R-07 | Idade em anos e meses ("63A 1M") | **Adotar** (relevante em pediatria). |
| R-08 | Filtros: tipo de campo do paciente, período por data de chegada (15 dias), modalidades em múltipla escolha, ordenação, **filtro personalizado salvo**, "Ocultar" filtros | **Adotar** filtros salvos por usuário e o recolhimento do painel de filtros. |
| R-09 | Abas "Exames" e "Desconsiderados" (lixeira) | **Adotar** como "Desconsiderados", reversível, com justificativa e auditoria; nunca apagar estudo. |
| R-10 | Topo: instituição, modo compacto, modo escuro | Modo compacto e escuro: P3. Troca de instituição no topo **não** (decisão: contas separadas por instituição). |
| R-11 | Estados por cor (vermelho/verde) sem texto; nomes cortados com "…" | Não adotar: a cor sempre vem acompanhada de texto; nome completo no (i) ou em duas linhas. |

## 3. Maquetes do proprietário: comparação com o VYONIX

**F02 — Técnico.** Já coincide com os quadros 1 e 2 (lista + painel lateral, checklist, Prioridade, Trocar médico, Salvar rascunho / Concluir conferência). O que acrescenta:
- contadores por situação (Todos, Recebidos, Aguardando conferência, Em laudo, Concluídos, Urgentes) → aplicado no quadro 1b;
- seleção múltipla de linhas → aplicada no 1b só para ações seguras (conferir em sequência, exportar lista);
- indicador "PACS online" → aplicado no 1b com a hora da última imagem;
- abas Dados do exame / Imagens / Histórico / Logs no painel → manter no quadro 2.

Divergências com o que foi aprovado: a maquete põe no menu do técnico **Viewer, Importação DICOM, Relatórios e Configurações**. O prompt mestre limita o menu a 5 itens e proíbe configurações globais → **decisão D-06**.

**F01 — Recepção.** Agenda do dia com navegação de data, busca, contadores (Confirmados, Em atendimento, Aguardando, Não compareceu), ação principal **Check-in** por linha, paginação 10/20/50/100. Bom modelo; base para o "Agenda de exames" do técnico (somente leitura) e para a recepção (INT-01/02).

**F19 — Coordenador do CDI.** Exames do dia, em andamento, pendências, urgentes; gráfico por modalidade; fila de urgentes com tempo; pendências; desempenho da equipe. Atenção: desempenho individual de médicos só para perfil autorizado (o médico vê apenas o próprio).

**F17 — Administrador da clínica.** Unidades, profissionais, serviços e exames, permissões, integrações (PACS, RIS, HIS). Coerente com o modelo atual de contas por instituição.

**F20 — Médico solicitante.** Meus exames solicitados, situação, Ver laudo / Ver agendamento. Condicionado ao mesmo controle do portal (BLK-06) e a vínculo verificado médico–paciente.

**F18 — Suporte** e **F16 — Administrador global.** Serviços, integrações, disco, alertas, tráfego DICOM, licenças, auditoria. Restrição proposta: **sem acesso a dados clínicos** (só métricas e logs sem identificação), acesso de suporte a uma instituição só com autorização registrada → **decisão D-07**.

## 4. Recomendações acumuladas (backlog)

| ID | Perfil | Recomendação | Origem | Prior. | Estado |
|---|---|---|---|---|---|
| REF-01 | Técnico, Médico | Botão "Abrir imagens ▾" com escolha do visualizador | R-02 | P2 | Protótipo 1b |
| REF-02 | Técnico, Coord. | Prioridade bloqueada com laudo em elaboração ou assinado, motivo visível; regra no backend | R-03 | P1 | Protótipo 1b; implementar |
| REF-03 | Todos internos | Dados do paciente em um clique, somente leitura, CPF mascarado, copiar registro | R-06 | P2 | Protótipo 1b |
| REF-04 | Todos internos | Idade em anos e meses | R-07 | P3 | Protótipo 1b |
| REF-05 | Técnico, Médico, Coord. | Filtros salvos por usuário + recolher filtros | R-08 | P2 | Protótipo 1b |
| REF-06 | Técnico, Coord. | Aba Desconsiderados (reversível, justificativa, auditoria, permissão) | R-09 | P2 | Protótipo 1b; decisão D-08 |
| REF-07 | Técnico | Contadores por situação nas abas | F02 | P3 | Protótipo 1b |
| REF-08 | Técnico | Seleção múltipla só para ações seguras | F02 | P3 | Protótipo 1b |
| REF-09 | Técnico | Indicador de recepção do PACS com hora da última imagem | F02 | P3 | Protótipo 1b |
| REF-10 | Recepção | Agenda do dia com Check-in na linha e contadores | F01 | P2 | Próximo protótipo |
| REF-11 | Coordenação | Painel operacional (urgentes com tempo, pendências, por modalidade) | F19 | P2 | Próximo protótipo |
| REF-12 | Médico solicitante | Exames solicitados com situação e laudo liberado | F20 | P2 | Após BLK-06 |
| REF-13 | Suporte / Admin global | Painéis técnicos sem dados clínicos | F16, F18 | P2 | Decisão D-07 |
| REF-14 | Todos | Modo compacto e modo escuro | R-10 | P3 | Backlog |

## 5. Decisões do proprietário pedidas por este lote

- **D-06**: o menu do técnico inclui Viewer, Importação DICOM e Relatórios (como na maquete F02) ou fica com os 5 itens do prompt mestre? Recomendação: 5 itens; Importação DICOM vira ação dentro de "Exames recebidos" com permissão própria.
- **D-07**: Suporte e Administrador global sem acesso a dados clínicos; acesso pontual a uma instituição só com autorização registrada e prazo. Recomendação: aprovar.
- **D-08**: quem pode "desconsiderar" um estudo (técnico com justificativa, ou só coordenação)? Recomendação: técnico solicita, coordenação aprova.
- **D-09**: os perfis 1–6 das maquetes entram no projeto de reformulação agora (protótipos) ou depois dos três perfis principais? Recomendação: protótipos de Recepção e Coordenação agora; Suporte/Admin global depois.

## 6. Próximos lotes

Novas fotos serão acrescentadas como Lote 2, 3… neste mesmo formato, com as recomendações somadas à tabela da seção 4.
