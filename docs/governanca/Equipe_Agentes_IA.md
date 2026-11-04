# Equipe de agentes especializados de IA — VYONIX Medical Platform

Implantação pedida pelo proprietário em 04/11/2026 04:09. Este registro distingue:
**CONFIGURADO** (definição existe e é válida) · **EXECUTADO** (recebeu e realizou tarefa real, com registro de
execução) · **VALIDADO** (resultado revisado e aceito pelo coordenador e/ou pelo proprietário).

## Agentes configurados (`.claude/agents/`, frontmatter YAML validado)
| Agente | Arquivo | Ferramentas | Atuação |
|---|---|---|---|
| A01 Arquiteto de Software | `a01-arquiteto.md` | Read, Grep, Glob, Bash | somente leitura |
| A02 PACS/DICOM | `a02-pacs-dicom.md` | Read, Grep, Glob, Bash | análise; edição só se a tarefa pedir |
| A03 RIS e Telelaudos | `a03-ris-telelaudos.md` | Read, Grep, Glob, Bash | análise; edição só se a tarefa pedir |
| A04 Segurança e LGPD | `a04-seguranca-lgpd.md` | Read, Grep, Glob, Bash | somente leitura; provas só no scratchpad |
| A05 UX/UI | `a05-ux-ui.md` | Read, Grep, Glob, Bash, Write, Edit | protótipos no canvas; nada definitivo em `web/src` sem aprovação |
| A06 Windows/DevOps | `a06-windows-devops.md` | Read, Grep, Glob, Bash | leitura; não dispara nem cancela CI |
| A07 QA e Testes | `a07-qa-testes.md` | Read, Grep, Glob, Bash | revisor independente |
| A08 Banco de Dados | `a08-banco-dados.md` | Read, Grep, Glob, Bash | somente leitura |

Todas as definições carregam as regras permanentes: não modificar o DICOM Print, dados só fictícios, nada
destrutivo, sem push/commit/CI, evidência obrigatória, distinguir teste local × CI × validação do proprietário.

### Limitação técnica observada (sem contornar)
A sessão do Claude Code (2.1.318) carregou a lista de tipos de agente ao iniciar. Chamar `a01-arquiteto`
pelo nome devolveu "Agent type not found" (tentativa registrada em 04/11 04:11). Às 07:23 a sessão recarregou e
os oito tipos (`a01-arquiteto` … `a08-banco-dados`) passaram a constar como acionáveis pelo nome. Os tipos personalizados passam a
ser acionáveis pelo nome numa sessão nova (a pasta também foi exposta na raiz de trabalho da sessão,
`/home/claude/.claude/agents` → `vyonix-dicomprint/.claude/agents`). **Nesta sessão**, cada agente é executado
como subagente real do tipo `general-purpose` que **lê e segue o seu arquivo de definição** e abre o relatório
com "AGENTE: A0x — definição lida".

## Coordenação
- Sessão principal = coordenadora: distribui, acompanha, integra alterações, roda testes, atualiza backlog.
- Paralelismo só entre tarefas independentes; agentes de revisão não editam o repositório; integração centralizada.
- Registros de execução: arquivos de transcrição em `~/.claude/projects/-home-claude/<sessão>/subagents/`.

## Execuções
### Missão 1 — auditoria coordenada da retirada do licenciamento (04/11/2026)
Lançadas às 04:12 em paralelo, como subagentes `general-purpose` que leram a própria definição (os tipos
personalizados ainda não estavam carregados). A07 e A08 pararam no limite de uso da conta (04:1x) e foram
**retomados com o mesmo contexto** às 07:23. Nenhum agente editou o repositório (provas só no scratchpad:
`agentes/a04_prova.py`, `tripwire.py`, `proof/test_proof_a07.py`).

| Agente | Situação | Principais achados (sev.) | Integração pelo coordenador |
|---|---|---|---|
| A01 Arquitetura | EXECUTADO · VALIDADO | DEPLOY ainda criava a pasta Licensing e dava permissão de escrita a Core/Worker (P1); CI `installation_id()` podia criar selo no cofre (P2); import de `vyonix.licensing` ao iniciar (P2); resíduos (P3) | plano sem pasta/ACL de licenciamento; CI só lê com selo existente; import só para tipagem |
| A04 Segurança/LGPD | EXECUTADO · VALIDADO | autenticação, permissões, RLS e auditoria intactos; `/system` expunha dados do servidor no modo cloud (P2); mensagens do DEPLOY com caminhos (P3); permissão na pasta do Print (P2, = A01) | `/system` restrito à operadora no cloud; versão do PostgreSQL só principal; caminhos mascarados |
| A06 Windows/DevOps | EXECUTADO · VALIDADO | 2.9 aceitava arquivo ilegível e não via ACL/registro; regravação do horário do Print podia dar falso erro (P2); atualização 0.2.0 podia ser pulada sem aviso (P2) | comparação com ACL, registro e "ilegível reprova", ignora só o registro de horário; workflow falha sem o instalador 0.2.0 e confere o SHA-256 |
| A07 QA (independente) | EXECUTADO · VALIDADO | sem CI da 0.3.0 (P0 até rodar); teste "sem licença" aceitava 403 no laudo (P1); faltava 403 por papel em módulos; teste do cloud parcial; classe após `__main__` | laudo exige 200/201; teste 403 por papel; teste do `overview` no cloud; classe reposicionada. Pendentes: e2e da tela do técnico, `Barrier` no teste de corrida, 2.13 com comparação da pasta |
| A08 Banco de Dados | EXECUTADO · VALIDADO | tabelas legadas preservadas; report_0012 segura; preenchimento sem médico (P2); subconsulta lenta (P3: 48,7 s → 50 ms); `release_expired` com erro de versão/cancelamento indevido (P2/P3) | preenchimento com médico (atribuição ou usuário autor) e `DISTINCT ON`; `release_expired` com trava por exame, ordem fixa e UPDATE condicional; teste `test_migration_report_starts` |

Testes depois da integração (locais): tests_platform **278 OK** (3 ignorados), tests_deploy OK, testes do DICOM
Print `tests/` OK (uma falha intermitente não identificada numa das 4 rodadas, com a máquina carregada pelos agentes;
3 rodadas seguintes OK; nenhum arquivo do DICOM Print alterado).

### Execuções anteriores (29/10/2026, tipo general-purpose, sem definição de agente)
Auditoria PACS/Viewer, Auditoria QA/Segurança, Auditoria RIS/Telelaudos, UX Fase A, UX Fase B — resultados
consolidados em `Registro_Aperfeicoamento.md` (A03/A04/A05) e `docs/ux/Fase_A_*`, `Fase_B_*`.
