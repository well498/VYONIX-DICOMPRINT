# VYONIX — Próxima ação executável e registro de tarefas

* **Atualizado em:** 2026-10-29 (fim da tarde) · ramo `develop`
* **Regra permanente do proprietário (29/10):** todo novo pedido é **acrescentado** ao planejamento; nada é
  cancelado, reiniciado ou descartado. P0 pode reordenar, preservando o progresso (justificativa registrada aqui).
* **Ponto exato de parada:** commit `efbae29` (P0 desinstalação/atualização/reparo/recuperação) enviado depois do
  fim do `deploy-windows` de `5a51301`; aguardando `deploy-windows` (critério 2.12) e o instalador de homologação
  (`flavor=homologacao`) para entregar a versão de teste e o kit de recuperação ao proprietário.

## Em execução
| Pri | Tarefa | Situação |
|---|---|---|
| P0 | Desinstalador que não removia; atualização direta; Reparar; recuperação da instalação atual; logs | Implementado (`efbae29`), testes locais OK; **CI Windows 2.12 em execução**; depois: versão de teste + kit `VYONIX_Kit_P0_Recuperacao.zip`; **resolvido só após validação no computador do proprietário** e Windows 10/11 (BLK-04) |
| P0 | Inicialização automática sem login, acesso pelo IP (bc9cf28) | Corrigido e aprovado no CI (2.10/2.11); **aguarda validação presencial** |

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
