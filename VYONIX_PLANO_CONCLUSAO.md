# VYONIX — Plano de conclusão (auditoria geral de 29/10/2026)

Escopo: VYONIX Medical Platform; **DICOM Print excluído**. IDs de [`VYONIX_PENDENCIAS_PRIORIZADAS.md`](VYONIX_PENDENCIAS_PRIORIZADAS.md).
Ordem pensada para reduzir risco: primeiro instalar e abrir com confiança, depois fechar o fluxo operacional, depois
produtividade e integrações, por fim evolução.

## Fase P0 — Instalação confiável e segurança básica

| # | Tarefa | Depende de | Critério objetivo de conclusão |
|---|---|---|---|
| 0.1 | IN-01: proprietário reinstala com o instalador `bc9cf28` (homologação ou comercial) | — | Atalho "VYONIX - Verificar funcionamento" mostra tudo OK; sistema abre em `https://localhost:8444` e, de outro computador, em `https://IP:8444`; relatório anexado |
| 0.2 | IN-02: reiniciar o computador | 0.1 | Após o login (ou sem login), em até 5 min, "Verificar funcionamento" OK sem intervenção |
| 0.3 | IN-03: Windows 10 e 11 limpos (BLK-04) | máquinas/VMs | 0.1 e 0.2 aprovados nos dois sistemas; registro em `docs/homologacao/` |
| 0.4 | SE-01: rotação da chave de emissão (BLK-01) | decisão do proprietário | Nova chave pública distribuída; documentos da chave antiga restritos à lista exportada; teste com documento forjado recusado |
| 0.5 | Corrigir qualquer falha encontrada em 0.1–0.3 | 0.1–0.3 | Falha reproduzida em teste automatizado e corrigida; CI Windows verde |

## Fase P1 — Fluxo operacional completo

| # | Tarefa | Depende de | Critério |
|---|---|---|---|
| 1.1 | Avaliação prática do roteiro de homologação pelo proprietário | 0.1 | Roteiro 1–11 executado; falhas registradas e corrigidas |
| 1.2 | NI-01: editor de laudo com formatação segura | — | Negrito, itálico, listas e tabelas no editor e no PDF; HTML sanitizado; e2e e testes de PDF |
| 1.3 | NV-03: teste com modalidade real ou simulador de fabricante (BLK-02) | equipamento | MWL, MPPS, C-STORE e (se suportado) storage commitment com o equipamento; roteiro HF-03 registrado |
| 1.4 | IN-04: assinatura de código (BLK-08) | certificado | Instalador assinado e verificado no CI |
| 1.5 | SE-02: teste de intrusão | 1.1 | Relatório sem achado crítico aberto |
| 1.6 | Decisões BLK-06 e BLK-14 (LGPD/CFM e assinatura digital) | proprietário | Parecer registrado; padrão de assinatura definido |
| 1.7 | Assinatura digital PAdES/ICP-Brasil | 1.6 | Laudo liberado com assinatura válida em validador oficial; testes com certificado de homologação |

## Fase P2 — Produtividade, integração e administração

| # | Tarefa | Depende de | Critério |
|---|---|---|---|
| 2.1 | NI-02 frases rápidas/presets e NI-03 modelos pessoais | 1.2 | Médico cria, usa e organiza por modalidade; permissão separada; testes |
| 2.2 | NI-04 revisão de laudo | — | Fluxo de segunda leitura com auditoria; testes |
| 2.3 | NI-07 comparação lado a lado no Viewer + NV-05 (pan, anotações, desempenho) | — | Atual e anterior abertos juntos; ferramentas exercitadas no CI viewer; estudo sintético grande abre em tempo definido |
| 2.4 | NI-06 HL7 ADT/ORM e NI-05 convênios | — | Mensagens de HIS simuladas criam paciente/pedido sem duplicar; testes |
| 2.5 | NI-08 alertas ativos | — | Atraso de laudo, disco crítico e falha de backup notificados; testes |
| 2.6 | PA-01 entrega e PA-02 histórico do paciente | 1.6 (LGPD) | Entrega auditada; tela de histórico com escopo por permissão |
| 2.7 | PA-04/PA-05 DICOM TLS e criptografia em repouso | — | TLS opcional testado; BitLocker exigido no assistente ou backup cifrado |
| 2.8 | NV-01/NV-02 encaminhamento e commitment com Orthanc real e no Windows | — | Critérios no CI deploy-windows |
| 2.9 | PA-03 produção financeira | NI-05 | Valores por procedimento/convênio e fechamento aprovado |

## Fase P3 — Evolução

Arquitetura híbrida (ADR-0014; depende de BLK-16), compartilhamento e rede de médicos entre instituições, MPR,
ferramentas por modalidade, exclusão por retenção (política aprovada), Patient Root, diretório de instalação, tela de
logs, .xlsx nativo.

## Dependências entre fases

P0 bloqueia a avaliação prática (1.1). 1.6 bloqueia 1.7, 2.6 e qualquer uso clínico. 1.2 antecede 2.1. Equipamento
(BLK-02) bloqueia 1.3. Nenhuma tarefa P2/P3 deve atrasar P0.
