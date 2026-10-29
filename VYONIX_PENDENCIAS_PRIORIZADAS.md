# VYONIX — Pendências priorizadas (auditoria geral de 29/10/2026)

Escopo: VYONIX Medical Platform; **DICOM Print excluído**. Origem de cada item: [`VYONIX_INVENTARIO_FUNCIONAL.md`](VYONIX_INVENTARIO_FUNCIONAL.md).
Prioridades: **P0** crítico (instalação, inicialização, segurança, funcionamento básico) · **P1** essencial ao fluxo
operacional completo · **P2** importante (produtividade, integração, administração) · **P3** evolução futura.
Requisitos essenciais e melhorias opcionais estão separados: P0/P1 são essenciais; P2/P3 não bloqueiam a homologação.

## 1. Não implementadas

| ID | Pendência | Módulo | Prior. |
|---|---|---|---|
| NI-01 | Editor de laudo com formatação (negrito, listas, tabelas) e saída segura no PDF | Editor | P1 |
| NI-02 | Frases rápidas, presets e textos básicos por médico/modalidade | Editor | P2 |
| NI-03 | Modelos pessoais do médico (com permissão) | Cadastro médico | P2 |
| NI-04 | Revisão de laudo (segunda leitura) | Telelaudo | P2 |
| NI-05 | Cadastro de convênios | RIS | P2 |
| NI-06 | Receptor HL7 v2 ADT/ORM (MLLP) | RIS | P2 |
| NI-07 | Comparação lado a lado no Viewer (protocolo de exibição com exame anterior) | Viewer | P2 |
| NI-08 | Alertas ativos (e-mail/mensagem: atraso de laudo, disco, falha de backup) | Administração | P2 |
| NI-09 | Teste de intrusão / revisão de segurança independente | Segurança | P1 |
| NI-10 | Compartilhamento de estudos entre instituições e rede de médicos entre instituições | PACS/Telelaudo | P3 |
| NI-11 | Ferramentas por modalidade no Viewer | Viewer | P3 |
| NI-12 | Instalação em diretório escolhido | Deploy | P3 |

## 2. Incompletas (parciais) e implementadas sem validação

| ID | Pendência | Estado | Prior. |
|---|---|---|---|
| PA-01 | Entrega do laudo ao paciente/solicitante (hoje: PDF, FHIR, HL7 ORU, DICOM PDF; sem portal ou envio) | Parcial | P2 |
| PA-02 | Histórico do paciente numa tela única (hoje: anteriores e linha do tempo por exame) | Parcial | P2 |
| PA-03 | Produção financeira por procedimento/convênio e fechamento mensal | Parcial | P2 |
| PA-04 | DICOM TLS opcional (Q/R e motor) | Parcial | P2 |
| PA-05 | Criptografia em repouso: documentar BitLocker como requisito ou cifrar backup | Parcial | P2 |
| NV-01 | Encaminhamento automático com Orthanc real e no Worker do Windows | Não validada | P2 |
| NV-02 | Storage commitment com modalidade real e Orthanc real | Não validada | P2 |
| NV-03 | Integração com modalidades reais (MWL, MPPS, C-STORE) | Não validada (BLK-02) | P1 |
| NV-04 | Tela de logs técnicos para suporte | Não validada | P3 |
| NV-05 | Viewer: pan, anotações, MPR e desempenho com estudo grande | Não verificada | P2 (MPR P3) |

## 3. Integrações pendentes

HL7 de entrada (NI-06); modalidades reais (NV-03); portal do paciente/envio (PA-01); sincronização edge → central
(ADR-0014, BLK-16); assinatura digital ICP-Brasil (BLK-14).

## 4. Defeitos conhecidos

Nenhum defeito reproduzível no CI de `d29d391`. Defeitos encontrados e corrigidos nesta fase: assistente abria
Documentos (`344ab09`); banco sem recuperação automática (`bc9cf28`); teste do Worker desatualizado (`4b7eb6a`).

## 5. Falhas de instalação

| ID | Pendência | Prior. |
|---|---|---|
| IN-01 | Confirmar a correção na instalação real do proprietário (instalador `bc9cf28`): instalar, abrir pelo atalho, acessar por `localhost` e pelo IP de outro computador | **P0** |
| IN-02 | Reiniciar o computador e confirmar que o VYONIX volta sozinho | **P0** |
| IN-03 | Repetir em Windows 10 e Windows 11 de mesa limpos (BLK-04) | **P0** |
| IN-04 | Assinatura de código do instalador (aviso "editor desconhecido") (BLK-08) | P1 |

## 6. Problemas de segurança

| ID | Pendência | Prior. |
|---|---|---|
| SE-01 | Chave de emissão de licenças comprometida ainda aceita (BLK-01) | **P0** (decisão do proprietário) |
| SE-02 | Teste de intrusão / revisão independente (NI-09) | P1 |
| SE-03 | DICOM sem TLS; banco, imagens e backup sem cifra própria (PA-04, PA-05) | P2 |

## 7. Testes ainda necessários

Reinicialização real (IN-02); Windows 10/11 (IN-03); modalidades e impressoras reais (BLK-02); carga do PACS e do
Viewer; Viewer: pan, anotações, MPR; encaminhamento e commitment com Orthanc real; navegadores além do Chromium;
avaliação prática de usabilidade pelo proprietário; teste de restauração em máquina diferente.

## 8. Dependências externas

Certificado de assinatura de código (BLK-08); certificados ICP-Brasil e padrão PAdES (BLK-14); equipamento DICOM ou
simulador de fabricante (BLK-02); máquinas Windows 10/11 (BLK-04); parecer jurídico sobre a distribuição do Orthanc
(BLK-07); especialista regulatório LGPD/CFM/ANVISA (BLK-06).

## 9. Decisões que exigem autorização do proprietário

BLK-01 (rotação da chave de emissão), BLK-06 (enquadramento regulatório), BLK-07 (Orthanc GPLv3 no produto),
BLK-08 (certificado de código), BLK-14 (assinatura digital), BLK-15 (recusar C-STORE de equipamento não cadastrado já
na associação), BLK-16 (sincronização edge → nuvem), política de retenção com exclusão, publicação de versões
(BLK-05), ensaios em campo (BLK-13).

## 10. Requisitos para homologação futura

1. IN-01 a IN-03 aprovados e registrados.
2. Roteiro de homologação executado pelo proprietário sem falhas abertas P0/P1.
3. NI-01 (editor) e NV-03 (modalidade real) concluídos.
4. Decisões BLK-01, BLK-06 e BLK-14 tomadas (sem elas, nenhum uso clínico).
5. Teste de intrusão (SE-02) sem achados críticos abertos.
