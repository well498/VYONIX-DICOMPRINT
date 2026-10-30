# VYONIX — Próxima ação executável e registro de tarefas

* **Atualizado em:** 2026-10-29 (fim da tarde) · ramo `develop`
* **Regra permanente do proprietário (29/10):** todo novo pedido é **acrescentado** ao planejamento; nada é
  cancelado, reiniciado ou descartado. P0 pode reordenar, preservando o progresso (justificativa registrada aqui).
* **Ponto exato de parada:** `f9c04e3` (+ documentos) enviado com `[skip ci]` para não cancelar os runs Windows
  `40944999029` (comercial, 78ce54b) e `40945047712` (homologação). Ao terminarem: registrar resultados por critério e
  disparar `deploy-windows` (ambos os sabores) em `f9c04e3`+, que inclui o novo critério **2.13** (recuperação com
  falhas, reexecução, reversão, falhas simuladas de migração e inicialização). **Kit e instalador só são entregues
  com 2.12, 2.13 e a homologação aprovados nesse commit.**

## Em execução
| Pri | Tarefa | Situação |
|---|---|---|
| P0 | Desinstalador que não removia; atualização direta; Reparar; recuperação da instalação atual; logs | Implementado (`efbae29`), testes locais OK; **CI Windows 2.12 em execução**; depois: versão de teste + kit `VYONIX_Kit_P0_Recuperacao.zip`; **resolvido só após validação no computador do proprietário** e Windows 10/11 (BLK-04) |
| P0 | Inicialização automática sem login, acesso pelo IP (bc9cf28) | Corrigido e aprovado no CI (2.10/2.11); **aguarda validação presencial** |

## Reformulação UX/UI (autorizada em 29/10 21:36) — `docs/ux/Projeto_Reformulacao_UX.md`
P3 (com correções P1 de acesso/permissões/usabilidade operacional); não interrompe o P0. Fases A (diagnóstico) e B
(referências brasileiras) em execução; C (arquitetura por perfil) e D (protótipos + mapas de navegação) depois,
**para aprovação** antes de qualquer substituição em massa.

## Correções de segurança da auditoria (29/10, `c725108`, testes locais; CI Linux pendente)
A05-001, A05-002, A03-001, A04-002, A04-003. Aguardando aprovação do proprietário: A04-001 (papel por unidade vale
para a organização — escalada de privilégio; P0), A05-003, A05-014, A05-015, A03-015, A04-007, A04-009.

## Diretriz permanente de auditoria e aperfeiçoamento (29/10 18:13)
`docs/governanca/Diretriz_Auditoria_Aperfeicoamento.md` (texto recebido truncado em "Util"). Registro único:
`docs/governanca/Registro_Aperfeicoamento.md`. Auditorias iniciais 03 (PACS/Viewer), 04 (QA/Segurança) e 05
(RIS/Telelaudos) em execução, somente leitura, sem interferir no P0; a 02 é contínua no P0; a 01 consolida.

## Acompanhamento P0 (aprovado pelo proprietário em 29/10 17:59)
Planilha oficial: `docs/homologacao/VYONIX_P0_Acompanhamento.xlsx`, gerada por `python tools/p0_planilha.py` a
partir de `docs/homologacao/P0_acompanhamento.json` (fonte única). A cada resultado de teste: atualizar o JSON
(situação, evidência, data), regenerar a planilha e esta seção no mesmo commit. Nunca marcar como aprovado o que
não foi executado.

## Resultados CI Windows (29/10)
| Run | Commit | Resultado |
|---|---|---|
| `40944999029` comercial | 78ce54b | 34 aprovados, 6 reprovados, 1 não executado. Os 6 vêm de uma só causa: o passo que fecha processos da pasta do programa encerrava o próprio `unins000.exe` (código −1) e a desinstalação seguia em segundo plano, derrubando os testes seguintes. Corrigido em `4bb8b0f` |
| `40945047712` homologação | 28d25ce (=78ce54b + docs) | 0a–9 aprovados (inclui atualização por cima de bc9cf28); 10–14 sem resultado visível (limite de 10 avisos do GitHub; agora há resumo único); 15 reprovado (mesma causa) |
| `40951093428` comercial / `40951161126` homologação | b22bcc4 | **em execução** (inclui 2.13) |

## Pedido de 29/10 17:50 — acompanhamento P0
| Item | Situação |
|---|---|
| 1. Resultados individuais de `40951093428`/`40951161126` (b22bcc4) | aguardando término |
| 2. Desinstalador: não encerra a si nem temporários; aguarda; só serviços do VYONIX; sem órfãos; erro se incompleto; testes sem corrida | Implementado em `457a6eb` (testes locais OK); **CI a executar após b22bcc4** |
| 3. Integridade além de contagem; DICOM/configurações preservados; bancos preexistentes protegidos | `457a6eb`: MD5 por tabela + sequências + estrutura + amcheck; inventário DICOM; reversão só de banco/cluster criado na execução |
| 4. Homologação sobre bc9cf28: migrações, serviços, verificação | `457a6eb` (passo 1 ampliado) |
| 5. Entrega: instalador, kit, Verificar funcionamento, procedimento, checklist, reversão, logs, versão/commit/limitações | após aprovação |
| 6. DICOM Print: testes dependentes de impressora/equipamento registrados à parte, não como falha do Platform | aplicado no relatório |

## Pedido de 29/10 17:05 — validação do procedimento de recuperação (P0)
| Item | Situação |
|---|---|
| 1. Diagnóstico estritamente não destrutivo + inventário do que pertence ao VYONIX | Implementado (`f9c04e3`); teste local; CI 2.13 (antes = depois) **a executar** |
| 2. Confirmação explícita com plano (serviços, processos, pastas, dados, backups, impactos, limites); nada alheio | Implementado; serviço alheio com o mesmo nome e processo alheio testados no CI 2.13 **a executar** |
| 3. Integridade do banco, backup consistente com configurações, prova de restauração, estado anterior, reversão | Implementado (pg_dump + restauração em banco temporário + contagens; cópia a frio SHA-256; `estado-anterior`; `Reverter_VYONIX`) — CI **a executar** |
| 4. Atualização após a recuperação (detecção, preservação, migrações, parada segura, serviços, verificação) | Coberto por 2.12/2.8; corrigido risco de a reversão apagar banco de estado desconhecido |
| 5. Testes: cancelamento, falha ao renomear, falha na remoção de serviço, falha na migração, falha na inicialização, restauração, reexecução | Escritos no CI 2.13 (migração/inicialização por falha **simulada**, declarado) — **não executados ainda** |
| 6. Entrega: instalador, kit, procedimento, checklist, coleta de logs, reversão | Documentos prontos (`Procedimento_Recuperacao_Instalacao_Proprietario.md`, `Checklist_Validacao_P0.md`); entrega **só após aprovação do CI** |

## Concluídas em 29/10 (com testes)
* Editor de laudos rico, DOCX com formatação, frases rápidas completas, modelos pessoais e continuidade, revisão e
  autoria das versões (`047408d`, `06e39e0`).
* BLK-15 simulado (recusa na associação) — aprovado no CI com Orthanc real (`1913882`); não ativado na instalação.
* Viewer: comparação, protocolos, escopo por vínculo opcional, histórico do paciente (`5a51301`; CI viewer aprovado).
* Menu único "Abrir imagens" com VYONIX Viewer, Weasis e Oviyam (desligados) (`77f02bc`).
* Análises: BLK-01 (escopo do licenciamento e alternativas), privacidade/continuidade de modelos, lacunas do Viewer,
  Weasis/Oviyam.

## Validação que só o computador do proprietário (ou uma VM própria) pode fazer
O CI do GitHub não permite reiniciar a máquina (o reinício encerra a execução). Por isso ficam **para a validação
presencial**, sem serem declarados aprovados: reinício real do Windows com os serviços subindo **sem login e sem
terminal** (C6/C7 do kit de validação), Windows 10/11 (BLK-04), recuperação da instalação atual com a ferramenta,
abertura real no Weasis. O CI cobre: serviços automáticos com conta de serviço, ordem de dependência e partida a frio
(tudo parado → iniciar), queda do banco e do processo, instalação, atualização por cima da versão anterior (bc9cf28),
reparo, desinstalação com o assistente aberto, reinstalação e ferramenta de recuperação.

## Pendentes (ordem)
| Pri | Tarefa | Dependência |
|---|---|---|
| P0 | Validação presencial: recuperar a instalação atual, instalar a versão de teste, atualizar, reparar, desinstalar, reinício sem login, acesso pelo IP | proprietário |
| P0 | Windows 10 e 11 | BLK-04 (máquinas) |
| P1 | Weasis: validar abertura real num Windows com o Weasis instalado (protocolo `weasis://`, certificado HTTPS confiável — sem desligar verificações), revogação/expiração/isolamento em uso real; requisitos das estações | proprietário (computador de teste) |
| P2 | Extensão VYONIX do OHIF: sincronização de zoom/pan e janela/nível na comparação, ferramentas por protocolo | proposta técnica antes (mudança estrutural moderada) |
| P2 | Oviyam: estudo de execução isolada e subordinada às permissões do VYONIX (sem Java/Tomcat na instalação atual) | se inviável, permanece desativado |
| P2 | Portal do paciente (abrir os próprios exames no navegador) | BLK-06 (LGPD/CFM) e segurança |
| P2 | Medição de desempenho com estudo volumoso no Viewer | — |
| P2 | Encaminhamento: reenviar imagens tardias; receptor HL7 ADT/ORM; DICOM TLS no Q/R | — |

## Aguardando decisão do proprietário
* BLK-01: alternativa para a chave (recomendada: separar a plataforma agora; Print depois) — nada destruído/revogado.
* Escopo das imagens por vínculo como padrão (hoje: `organization`, comportamento homologado).
* BLK-15 na instalação; BLK-16; BLK-14; BLK-06; BLK-04; BLK-02; BLK-08; publicação.
