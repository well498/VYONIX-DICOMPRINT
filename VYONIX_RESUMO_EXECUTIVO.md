# VYONIX Medical Platform — Resumo executivo da auditoria (29/10/2026)

**Escopo:** plataforma VYONIX (PACS, Viewer, RIS, Telelaudo/Laudos, Administração, Instalação, Edge). **DICOM Print
excluído.** Base: repositório `develop` em `d29d391`, 281 testes automatizados, CI aprovado (platform 279/0/0 com
PostgreSQL e Orthanc reais; Windows 34/0/1; Viewer; homologação 13/13). Nenhuma validação clínica existe.

## 1. Pronto e validado (testes automatizados com componentes reais)

* **PACS:** recepção DICOM, armazenamento com SHA-256, índice isolado por instituição, DICOMweb (STOW/QIDO/WADO),
  C-ECHO/C-FIND/C-MOVE/C-GET, nós DICOM com histórico e recepção só de equipamentos cadastrados, quarentena,
  duplicidade, backup verificado e restauração, integridade contínua, auditoria.
* **Viewer:** abrir estudo, navegar imagens e séries, janela/nível, zoom, girar, inverter, medir distância.
* **RIS:** pacientes, procedimentos, pedidos, agenda por sala, worklist, MPPS, Central de Exames, preparação técnica,
  fluxo configurável, linha do tempo, exames anteriores.
* **Telelaudo:** fila por vínculo, distribuição manual/fixa/equilibrada, prioridades e prazos, laudo, adendos,
  liberação com senha e versões imutáveis.
* **Laudos:** modelos versionados, importação Word, identidade visual, PDF, assinatura manuscrita autorizada.
* **Usuários e permissões, cadastro médico, Minha Produção:** completos nos requisitos levantados.
* **Instalação Windows:** serviços automáticos, recuperação de falhas (inclusive banco derrubado), diagnóstico de
  inicialização, acesso por localhost e pelo IP, atualização e desinstalação — **no Windows Server do CI**.

## 2. Implementado, mas precisa de testes

Encaminhamento automático e storage commitment (só com motor dublê); integração com modalidades reais; **instalação
na máquina do proprietário** (corrigida e validada no CI, ainda não confirmada na prática); logs técnicos.

## 3. Parcial

Editor de laudo (texto simples); entrega do laudo (sem portal/envio); histórico do paciente; HL7 (só saída);
produção financeira (só tabela por modalidade); criptografia (sem DICOM TLS e sem cifra de banco/imagens/backup).

## 4. Não desenvolvido

Formatação no editor, frases rápidas/presets, modelos pessoais do médico, revisão de laudo, convênios, HL7 de
entrada, comparação lado a lado no Viewer, alertas ativos, compartilhamento entre instituições, teste de intrusão.
Arquitetura local+nuvem: só proposta e protótipo, desabilitada.

## 5. Problemas críticos

1. Falha de instalação de 28/10: **causa raiz comprovada e corrigida, validada no CI; falta a confirmação prática**
   (reinstalar, reiniciar, Windows 10/11).
2. Chave de emissão de licenças comprometida ainda aceita (BLK-01).
3. Sem assinatura digital ICP-Brasil e sem avaliação LGPD/CFM: impedem uso clínico.
4. Nenhum teste com equipamento DICOM real.

## 6. Percentual estimado

Sobre 135 itens do inventário, pesos iguais: **implementação ≈ 78%**, **validação automatizada ≈ 71%**. A estimativa
compara módulos, **não mede prazo nem prontidão clínica** (confiabilidade baixa para planejamento). Mais adiantados:
Usuários (100%), PACS (91%), Produção (90%); mais atrasados: Edge (38%), Viewer (57%), Segurança (58%).

## 7. Ordem recomendada

P0: confirmar a instalação (reinstalar, reiniciar, Windows 10/11) e rotacionar a chave (BLK-01) → P1: avaliação
prática do roteiro, editor com formatação, teste com modalidade real, assinatura de código, teste de intrusão,
decisões regulatórias e assinatura digital → P2: frases rápidas, revisão, comparação no Viewer, HL7/convênios,
alertas, criptografia → P3: Edge, rede entre instituições, MPR. Detalhes em `VYONIX_PLANO_CONCLUSAO.md`.

## 8. Bloqueios que dependem do proprietário

BLK-01 chave de emissão · BLK-04 máquinas Windows 10/11 · BLK-02 equipamento DICOM · BLK-06 LGPD/CFM/regulatório ·
BLK-07 parecer sobre o Orthanc · BLK-08 certificado de código · BLK-14 assinatura digital · BLK-15 recusa na
associação · BLK-16 sincronização com a nuvem · política de retenção com exclusão · publicação e ensaios em campo.
