# Desligamento de médicos, redistribuição e Transferência Excepcional de Responsabilidade Médica

Pedido do proprietário: 04/11/2026 21:51. Prioridade **P1** (fluxo clínico e permissões). Situação: **desenho
concluído (A03) e protótipos apresentados (A05); aguardando respostas do proprietário antes de implementar a
interface.** Nada implementado ainda. VYONIX DICOM Print não é afetado.

## Regras pedidas (resumo)
* **A — atribuído, laudo não iniciado:** redistribuir a médico habilitado mantendo prioridade e prazo; registrar
  anterior, novo, motivo, responsável e horário; notificar o novo médico; desligado sem acesso. Troca manual continua
  exclusiva do Técnico em Radiologia.
* **B — iniciado, não assinado:** Transferência Excepcional (desligamento definitivo, falecimento, perda de
  habilitação, impossibilidade permanente comprovada) com motivo documentado, verificação do médico original,
  autorização específica e auditada do **gestor clínico** (não qualquer administrador), rascunho original encerrado e
  preservado, **novo rascunho** do novo médico, revisão independente das imagens, histórico só com autorização,
  proteção contra concorrência. Não pode contornar o bloqueio normal; ninguém assina o rascunho do anterior.
* **C — assinado:** sem transferência de autoria; retificação ou adendo.
* Desligamento **por instituição** (contas independentes de outras instituições intactas), prévia das pendências,
  bloqueio de novas atribuições, revogação de sessões/permissões do vínculo, nada excluído; prazos não reiniciam; sem
  substituto → fila de pendências.

## Lacunas atuais encontradas pelo A03 (código `d7ed073`)
| Sev. | Lacuna |
|---|---|
| P1 | Encerrar vínculo/desativar médico só grava o campo: atribuições abertas continuam com o desligado e o exame fica preso (o novo controle de autoria recusa outros médicos) |
| P1 | Compartilhamento temporário (ExamShare) mantém acesso de médico desativado cujo usuário segue ativo |
| P1 | Reencaminhamento e trocas manuais recalculam o prazo (`agora + SLA`) em vez de manter o original |
| P1 | Laudo assinado de médico desligado: ninguém consegue registrar adendo |
| P2 | Fim de vínculo inclusivo (acesso até a meia-noite); revisão presa com revisor desligado; delegação de assinatura não limpa; pendência sem prazo na tela |

## Desenho proposto (A03)
* **Um laudo por estudo é mantido** (índice único e várias consultas dependem disso). O rascunho antigo é arquivado
  em `report.draft_archives` (só SELECT/INSERT, com SHA-256) e o mesmo laudo é reaberto vazio para o novo médico.
* `report.responsibility_transfers` (pedido → aprovação/recusa → execução; UPDATE só de colunas de estado; índice
  único parcial impede duas transferências ativas por exame) e `report.offboardings` (prévia e execução).
* Responsável efetivo = destino da última transferência executada; senão quem iniciou (`report_starts` intocado).
* **Gestor clínico** como papel verificado por código (padrão da exclusividade do técnico): o administrador `*` não
  passa; quem pede não aprova; aprovador não pode ser origem nem destino; senha confirmada na aprovação.
* Notificação: evento `report.transfer.executed.v1` + comentário de sistema no exame (não há módulo de notificação).
* 14 testes mapeados (redistribuição, bloqueio comum, transferência autorizada/recusada, rascunho preservado, novo
  rascunho, assinatura não transferível, assinados preservados, uma só instituição, sessões revogadas, prazos,
  concorrência, auditoria, migração).

## Perguntas ao proprietário (A03 + A05)
1. Quem é o **gestor clínico autorizado** (diretor técnico médico? perfil novo?) e quem pode designá-lo — um
   administrador pode se autodesignar? (recomendação: exigir segundo administrador ou a operadora).
2. Quem **pede** a transferência excepcional (coordenação/quem distribui, técnico, administrador)?
3. Quem autoriza o novo médico a **consultar o rascunho anterior**, e o acesso expira?
4. Laudo "aguardando correção" (devolvido, não assinado) segue a transferência excepcional?
5. Quem cuida da **fila de pendências** e em quanto tempo?
6. Desligamento pode ser concluído com laudos ainda bloqueados, ou tudo deve ser resolvido antes?
7. **Adendo em laudo assinado por médico desligado**: quem assina e como se identifica?
8. Desligar só o vínculo médico ou a conta inteira quando o usuário tem outros papéis na instituição?

Protótipos (A05, não implementados): 5 telas — desligamento, redistribuição, transferência excepcional, painel do
novo médico, histórico e auditoria. Pontos para validação jurídica e clínica: papel do gestor clínico perante o
CFM, independência da revisão, retenção dos rascunhos arquivados (LGPD), responsabilidade durante a pendência.
