# Regra definitiva — Trocar médico e prioridade (04/11/2026)

Origem: mensagens do proprietário de 04/11/2026 02:56 (bloqueio após início do laudo) e 02:59 (exclusividade do
Técnico em Radiologia). Estado: **IMPLEMENTADO no código (commit deste registro), testes locais aprovados; CI
Windows/Linux pendente; não validado no computador do proprietário.**

## Regra
1. Somente o **Técnico em Radiologia** (papel `tecnico` atribuído na unidade do exame ou em todas) troca o médico
   responsável e altera a prioridade (Rotina / Prioritário / Urgente).
2. Só **antes do início efetivo do laudo**. Depois, ambas ficam bloqueadas para todos, inclusive o técnico.
3. Administrador, Coordenador do CDI, Administrador da clínica, Médico e demais perfis **não** executam nem
   autorizam. A acumulação de papéis (inclusive administrador com `*`) não concede.
4. Justificativa obrigatória; auditoria com usuário, data/hora, valor anterior e novo.
5. Sem exceção automática para urgência; procedimento excepcional a definir e aprovar.

## O que é "início efetivo do laudo"
O médico abre o laudo para elaborar (cria o rascunho — `POST /report/reports`). Nesse momento o sistema grava
`report.report_starts` (horário, quem iniciou, médico responsável, prioridade vigente) na mesma transação.
Abrir imagens, consultar a ficha, a linha do tempo ou os anteriores **não** inicia o bloqueio.

## Garantias implementadas
| Garantia | Como |
|---|---|
| Backend, não só tela | `vyonix/ris/exclusive.py` (papel `tecnico`) e `vyonix/report/lock.py` (início) em todas as rotas: `/ris/prep/{id}/priority`, `/ris/prep/{id}/physician`, `/report/assignments`, pedidos `doctor_change`/`priority_request`, reserva (`claim`) e desistência (`release`) |
| Bloqueio permanente | tabela só com SELECT/INSERT para o aplicativo (REVOKE ALL + GRANT SELECT, INSERT); fechar o editor, mudar status, revisar ou assinar não removem; laudo existente sem registro também conta |
| Concorrência | trava de transação por exame (`pg_advisory_xact_lock`) no início do laudo e em cada alteração: a alteração espera e é recusada se o laudo começou |
| Distribuição automática | não atribui exame com laudo iniciado; reserva vencida com laudo iniciado é mantida |
| Atualização | migração `report_0012` cria o registro para todo exame que já tem laudo (origem `migracao`), sem alterar dados existentes |
| Mensagem | "Alteração indisponível: laudo já iniciado" (API 409 `report_started` e telas) |
| Visualização | lista e ficha do técnico, fila de laudos: situação, médico responsável, prioridade, horário de início do laudo e aviso de bloqueio em texto; atualização automática (15–20 s) sem recarregar a página |

## Mudanças em relação ao que existia (registradas)
- Antes: coordenação/administração alteravam prioridade (`ris.exam.priority`) e atribuíam (`report.assign`); o
  técnico só **solicitava**. Agora: só o técnico efetua; os pedidos à coordenação saíram da tela do técnico.
- Os quadros de protótipo 11 (Coordenação) deixam de ter aprovação de prioridade e troca de médico; a aprovação
  de "Desconsiderar estudo" continua com a coordenação (D-08).
- A tela "Laudos" deixou de ter Atribuir/Reatribuir.
- Testes existentes ajustados à regra nova: `test_ris_prep` (prioridade), `test_report_queue` e
  `test_ris_workflow` (atribuição pelo técnico), `test_e2e_web` passo 7 (coordenação não vê Atribuir).

## Testes de regressão novos — `tests_platform/test_report_start_lock.py`
1. Só o técnico altera; admin, coordenação, médico e usuário com papéis acumulados recebem 403 `technician_only`;
   justificativa obrigatória; auditoria com anterior/novo.
2. Técnico de outra unidade não altera.
3. Início do laudo bloqueia prioridade, troca (2 rotas), pedidos e reserva por outro médico; persiste após
   liberar/assinar; evento `report.started` único.
4. O papel do aplicativo não consegue apagar nem alterar o registro de início.
5. Alteração simultânea ao início do laudo espera e é recusada.

## Decisões confirmadas pelo proprietário (04/11/2026 03:21)
- Primeira atribuição manual: exclusiva do Técnico em Radiologia. Distribuição automática continua (regras da
  instituição).
- O médico assume exame **sem atribuição**, com autorização na unidade e **sem laudo iniciado**; não assume exame
  atribuído a outro (409 `already_assigned`). Implementado de forma estrita: exame com laudo iniciado não pode ser
  assumido por ninguém. Se um exame com laudo iniciado for devolvido para correção e reencaminhado, o sistema
  devolve a atribuição ao **mesmo** médico que iniciou (auditado), sem troca de responsável.
- Atribuições e reservas auditadas (`report.assign`, `report.reservation`); atribuições simultâneas serializadas
  por exame + índice único de atribuição aberta (teste de corrida).
- Prazos iniciais: Rotina 48 h, Prioritário 4 h, Urgente 1 h. **Configuráveis por instituição** com a permissão
  específica `report.sla.manage` (rota `PUT /report/sla`, justificativa obrigatória; a rota genérica de
  configurações também exige essa permissão). Validação: Urgente ≤ Prioritário ≤ Rotina.
- Sem efeito retroativo: prazos já calculados não mudam; só com a regra explícita `apply_to_open` (justificativa,
  auditoria `report.sla.reapplied` com cada prazo anterior e novo). O painel de atraso usa o prazo gravado.
- Testes: `tests_platform/test_report_sla_distribution.py` (3). Total local: 269 testes OK (3 skipped).

## Pontos anteriores (resolvidos)
- **Atribuição inicial manual**: tratada como "trocar médico" (só técnico). A distribuição automática do sistema e a
  reserva pelo próprio médico de exame livre continuam. Confirmar.
- **Médico que desiste** de um exame depois de iniciar o laudo: bloqueado (seria troca de responsável).
- **Rótulos**: routine=Rotina, urgent=Prioritário, stat=Urgente (prazos atuais 48 h / 4 h / 1 h).
