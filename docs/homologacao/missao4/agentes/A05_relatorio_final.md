# A05 — Relatório final (UX/UI) · Missão 4 · Fase 4

**O que eu fiz:** li o front-end e as permissões em `develop` (somente leitura) e escrevi `A05.md` (mapa de menus, roteiro, suspeitas). Olhei as 3 capturas do coordenador (Sistema, Painel do técnico com 409, Laudos a 375 px). Não usei a instância, não rodei testes e não alterei arquivos do repositório. A instalação roda a 0.3.1; eu li o `develop`.

## Status por item
| Item | Status | Base |
|---|---|---|
| Menu do admin = 15 itens, sem "Administração VYONIX" | **APROVADO** | Visto pelo coordenador; bate com `app.tsx:24-43` |
| Faixa de homologação em todas as telas | **APROVADO** | Capturas; `app.tsx:57,127` |
| Menus dos outros 9 perfis e do demo.multi | **BLOQUEADO** | A SPA não recarrega ao trocar de usuário e o iframe é bloqueado. Para destravar: recarregar a página (F5) após cada login, ou um navegador/perfil por usuário |
| S1–S5, A1–A6 (perfis sem caminho, ações por unidade) | **BLOQUEADO** | Dependem de entrar como cada perfil; nem confirmadas nem refutadas |
| T1–T13, F1–F9 (termos e formulários) | **A EXECUTAR** | Não foram percorridos na Fase 4 |
| Responsividade 375 px: sem rolagem horizontal da página | **APROVADO** (admin) | Coordenador |
| Laudos alarga para 499 px | **REPROVADO** | Causa provável: `.page-actions` sem `flex-wrap` (`styles.css:64`) com 5 botões de cabeçalho (`reports.tsx:94-103`); `.filters` também não quebra linha (`styles.css:79`) |
| Painel do técnico: GET `/ris/prep` com 409 e contadores zerados | **REPROVADO** (intermitente) | Na captura: fila = 0, mas "Estudos recebidos no PACS" = 21. Hipótese **não testada**: o GET renova a validade da sessão (`auth/service.py:449-451`). `AuthSession` tem controle de versão (`db/base.py:50`, `auth/models.py:64`). A tela dispara 3 GETs ao mesmo tempo (prep, technician-panel, sites); dois gravam a mesma linha de sessão, um recebe `StaleDataError` → 409 (`api/app.py:121-125`) |
| Agenda vazia por padrão | **REPROVADO** (UX) | `schedule.tsx:60` (`done:false`): recebidos/concluídos ficam ocultos e a mensagem de vazio não diz isso |
| Texto "A licença define quantas unidades…" | **REPROVADO** | `sites.tsx:18`; contradiz Sistema ("A plataforma não usa licença") |
| Sistema leva 4–6 s; avisos de backup do PACS | **A EXECUTAR** (não analisado) | Os avisos são coerentes com a pasta de backup inexistente; a causa da lentidão não foi investigada |

## Melhorias propostas (prioridade; nada implementado, depende de aprovação)
1. **P1** — Painel do técnico: um GET não deve devolver 409. Renovar a sessão sem controle de versão (ou ignorar o conflito ao renovar) e, na tela, não zerar os contadores quando há erro. Primeiro reproduzir com testes concorrentes locais.
2. **P1** — Repetir a inspeção dos 10 perfis com F5 após cada login ou um navegador por usuário; prioridade para gestor_telelaudos (S1/S2), financeiro (S3) e demo.multi (A1).
3. **P2** — Laudos a 375 px: permitir quebra de linha nos botões do cabeçalho e nos filtros (ou agrupar os 5 painéis num menu "Ferramentas").
4. **P2** — Agenda: deixar claro que o período não traz recebidos/concluídos (ex.: "3 exames ocultos — mostrar") ou incluí-los por padrão.
5. **P2** — Padronizar os termos (prioridade, situação, "Número de acesso", chegada) e traduzir os valores crus (T1–T3).
6. **P3** — Unidades: trocar o texto da licença. Sistema: carregar por partes e mostrar o progresso.
7. **P3** — Painel do técnico a 375 px: transformar a tabela larga em cartões, como já é feito na fila.
