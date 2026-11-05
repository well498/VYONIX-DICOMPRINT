# A04 — Relatório final de segurança/LGPD (Missão 4, VYONIX 0.3.1, instância desktop-3qf85g7)

**O que o A04 fez:** leu o código 0.3.1 (sem diferenças em `vyonix/` e `web/src` desde d1af7f2); fez a prova local no Linux
(`scratchpad/agentes/a04_m4_prova.py`, dados fictícios, 1 teste OK); escreveu a matriz `A04.md`; analisou as evidências
do coordenador (`export/log_testes.tsv`: 318 verificações, 313 ok e 5 divergências; `VYONIX_DEMO_EXPORT_20261105.json`:
479 eventos de auditoria). O A04 **não acessou a instância**: os testes reais foram feitos pelo coordenador.

| Área | Status | Base (evidência real) |
|---|---|---|
| Autenticação | **APROVADO** | senha errada 401 e usuário inexistente 401 com a mesma mensagem (T-SEC-PWD-ERR/ENUM); 403 `stage` antes da troca (T-SEC-STAGE); senha fraca 422; troca obrigatória 200 nos 14 usuários (PWCHG); trilha `auth.login_failed` com reason `password`/`unknown` |
| Sessões | **BLOQUEADO** (parcial) | logout 200 e depois /auth/me 401 (T-SEC-LOGOUT/2); CSRF ausente 403 (T-SEC-CSRF). Flags HttpOnly/Secure/SameSite não verificadas; invalidação do token no servidor só provada localmente |
| Permissões por perfil | **REPROVADO** | ~150 casos permitido/proibido conferem (ADM, SUP, CDI, TECG, MULTI, SUP2, TG…), incluindo `technician_only`, `self_roles` e `operator_only`; porém o financeiro lê o preparo e a timeline clínica (T-PRM-FIN-09/10 = 200) e a recepção lê o preparo (T-PRM-REC2-11 = 200) |
| Unidades | **REPROVADO** | `site_id = null` em todos os estudos (export); técnico da Matriz preparou e encaminhou estudos de pedidos de qualquer unidade (T-RIS-B3); multi age como técnico em estudo sem unidade (T-PRM-MULTI-05/06); médico 02 com fila vazia (T-UNI-05) e WADO de estudo fora do escopo = 200 (T-UNI-MED02-04) |
| IDOR | **APROVADO** (escopo testado) | IDs inexistentes → 404 (paciente, laudo); médico 02 → 403 `out_of_scope` em preparo/laudo (MED02-01..03). Exceção: imagens (ver Unidades). Isolamento entre instituições não testável (edge com 1 organização) |
| Auditoria | **APROVADO com ressalva** | `audit/verify` `{"ok":true,"broken":[]}`; eventos de login, falha, troca, logout, abertura de estudo, liberação e adendo presentes. Ressalvas: 403 e leituras de paciente não ficam registrados; liberação e adendo gravam o **nome exibido** do médico como ator e a API não devolve `actor_id` (routes_report.py:342,358) |
| Exposição | **APROVADO** | cabeçalhos de /health (CSP, XFO DENY, nosniff, no-referrer, HSTS, no-store, sem `server`); /users sem senha/token. /health público mostra a versão (P3) |

**Achados confirmados na instância**
- **P1 F-01:** estudos sem unidade; o isolamento por unidade não funciona (técnico, multi e médico 02).
- **P1 F-02:** financeiro e recepção leem os dados clínicos do preparo; o financeiro também lê a timeline. Anexos e comentários: só prova local.
- **P2 F-03:** médico 02 abre imagens fora do vínculo (`pacs/viewer.access=organization`).
- **P2 F-04:** 403 e leituras de prontuário sem trilha (LGPD).
- **P2 F-10 (novo):** o ator da liberação de laudo é o nome exibido (pode ser alterado) e a API não expõe o `actor_id`; o filtro `actor=demo.` não encontra liberações.
- **P2 OPS:** a senha do admin do proprietário trafegou no chat → **trocar já** e encerrar as sessões.
- **Observação:** `tecnico-cdi` teve 4 falhas de login (`failed` 1 e 2) e `JoaoVictor` 1, contas do proprietário fora dos testes; conferir com ele.

**Recomendações:**
- Atribuir unidade na entrada do estudo (nó PACS ou pedido) antes de qualquer declaração de isolamento.
- Exigir `ris.exam.prepare`/`report.read` no detalhe do preparo, nos anexos, na timeline e nos comentários.
- Usar `linked` no viewer só depois de F-01.
- Auditar negações e leituras de prontuário; gravar login + `actor_id` nos eventos de laudo.
- Verificar as flags do cookie no DevTools pelo proprietário.
