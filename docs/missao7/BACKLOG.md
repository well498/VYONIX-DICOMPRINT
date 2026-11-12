# Backlog persistente — VYONIX Medical Platform

Atualizado em 12/11/2026 (`develop` 4014570). Prioridades: P0 segurança, isolamento, instalação e integridade; P1 fluxos clínicos; P2 integrações; P3 melhorias visuais.

| # | Pri. | Item | Responsável | Depende de | Bloqueio | Evidência / situação |
|---|---|---|---|---|---|---|
| 1 | P0 | Isolamento por unidade no backend | A04, A07, A08 | — | — | Feito; em `develop`; CI aprovado |
| 2 | P0 | Reconferência final da A04 sobre as correções N1–N12 e as mudanças de 12/11 | A04 | 1 | — | A fazer |
| 3 | P0 | Testes dedicados para N4, N7, N8, N9, N11 e N12 | A07 | 1 | — | A fazer |
| 4 | P0 | Simulação somente leitura dos 20 exames DEMO | A08 | Computador do proprietário acessível | Computador inacessível em 12/11 | Autorizada; não executada |
| 5 | P0 | Vinculação definitiva dos exames antigos | A08 | 4 | Aprovação do proprietário sobre a simulação | — |
| 6 | P0 | Liberação da 0.3.2 (número de versão, notas, instalador) | A06 | 2, 3, critérios 4 e 8 | Autorização do proprietário | Bloqueada |
| 7 | P0 | Instalador: correção `runascurrentuser` | A06 | — | — | Pendente desde a Missão 4 |
| 8 | P0 | Publicar o instalador 0.3.1 como release (artefato expira em 05/12/2026) | A06 | — | Decisão do proprietário | O CI de atualização depende desse artefato |
| 9 | P0 | Administrador principal (até 3, nunca zero) | A04, A05 | — | Ramo `usuarios-admin-principal` quebra 2 testes | Em andamento (WIP 7021593) |
| 10 | P0 | Trocar a senha do administrador (apareceu na conversa) | Proprietário | — | — | Pendente |
| 11 | P0 | Backup e reinício controlado da homologação (Missão 4) | Proprietário | — | — | Scripts entregues; aguardando execução |
| 12 | P1 | Central de Exames do Técnico (Missão 7, etapas 3–5) | A03, A05 | Aprovação do protótipo "1c" e respostas (rótulos de prioridade) | Aprovação do proprietário | Protótipo entregue |
| 13 | P1 | Editar usuário e "Minha conta" para todos os perfis | A05 | 9 | — | Protótipos 13 e 14 entregues |
| 14 | P1 | Botões por exame conforme a unidade (frontend) | A05 | 1 | — | A fazer |
| 15 | P1 | Portal Único do Paciente (arquitetura aprovada, 10 regras) | A01, A03, A04, A05, A07, A08 | 6 | — | Arquitetura rascunhada; modelo de dados a fazer |
| 16 | P1 | Unidade obrigatória no cadastro de equipamento DICOM | A02 | 1 | Decisão do proprietário | Proposta |
| 17 | P2 | Compartilhamento excepcional entre unidades | A04 | ADR-0015 | Aprovação específica | Só desenho |
| 18 | P2 | Permissão administrativa de faturamento com dados mínimos | A03 | — | Necessidade a confirmar | Não criada |
| 19 | P2 | Compartilhamento entre instituições (fluxo próprio) | A01, A04 | 15 | — | Não iniciado |
| 20 | P2 | Missão 3: decisões D1–D9; Missão 2: G-1 a G-7; desligamento (8 perguntas) | Proprietário | — | Respostas do proprietário | Pendentes |
| 21 | P3 | Resumo de `access.denied` descartados; revogar tokens do visualizador na troca de papéis | A04 | — | — | A fazer |

O VYONIX DICOM Print não foi modificado.
