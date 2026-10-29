# Estudo de referências — dcm4chee Archive 5 e linha J4Care SMooTH × VYONIX

Data: 28/10/2026 · Ramo `develop` · Autor: equipe de desenvolvimento VYONIX (Claude) · Situação: **estudo técnico
interno**; não é declaração de conformidade nem de equivalência com produtos de terceiros.

## 1. Escopo, fontes e cuidados

**Objetivo.** Usar o dcm4chee Archive 5 (código aberto) e a linha comercial J4Care SMooTH como **referência de
maturidade** para evoluir o VYONIX, sem copiar código, telas, identidade visual ou componentes comerciais, e sem
substituir o Orthanc, o PostgreSQL ou o PACS atual.

**Fontes consultadas (28/10/2026).**

| Fonte | O que foi aproveitado |
|---|---|
| dcm4chee-arc-light — repositório e wiki (github.com/dcm4che/dcm4chee-arc-light) | Visão geral de funcionalidades; *storage commitment* disparado por exportação (wiki "Export Triggered Storage Commitment") |
| Declaração de conformidade do dcm4chee (dcm4chee-arc-cs.readthedocs.io, "Storage Application Entity") | Política de duplicados, coerção de atributos, notas de rejeição (IOCM), *storage commitment* só após releitura com checksum |
| web.dcm4che.org/dcm4chee-arc-light e /solutions | Lista de funcionalidades (MWL, MPPS, UPS, IAN, HL7 ADT/ORM/OMG/ORU, multiorganização, auditoria, HA, XDS-I) e relação SMooTH × dcm4chee |
| www.j4care.com | Descrição pública de SMooTH VNA, Viewer, VNEdge e VNIN |
| advantageaustria.org (perfil J4Care) | Contexto da empresa e referências (arquivos regionais e nacionais) |

**Limites desta análise.**
* A linha **SMooTH é comercial**. O site descreve funcionalidades em nível de marketing; detalhes internos
  (protocolos de sincronização, *failover*, regras de *prefetch*) **não estão publicados**. Nada aqui assume que
  recursos SMooTH existam no dcm4chee aberto.
* O dcm4chee aberto é distribuído sob licença tripla de código aberto (MPL 1.1 / GPL 2.0 / LGPL 2.1, conforme os
  cabeçalhos do código e a página de soluções do projeto para componentes da família). **Nenhum código, esquema,
  configuração LDAP ou tela foi copiado.** Toda implementação do VYONIX citada abaixo é própria.
* Comparação feita contra o **repositório real** do VYONIX (commit `69459b5`), não contra planos.

## 2. O que cada referência é

| Produto | Natureza | Papel |
|---|---|---|
| **dcm4chee Archive 5** | Código aberto (Java EE/WildFly, LDAP de configuração, Keycloak, PostgreSQL etc.) | Arquivo PACS/VNA: DIMSE, DICOMweb, MWL, MPPS, UPS, *storage commitment*, IAN, HL7, regras de exportação/roteamento, retenção, auditoria, UI de administração, multiorganização, alta disponibilidade |
| **SMooTH VNA** | Comercial (J4Care), baseado na edição *Enterprise* do dcm4chee | VNA central: imagens + documentos XDS, FHIR e patologia; de servidor único a datacenters ativo/ativo |
| **SMooTH Viewer** | Comercial | Visualizador web *zero-footprint* de imagens e documentos |
| **SMooTH VNEdge** | Comercial | Borda: *cluster* de três mini-PCs no centro remoto, continua operando sem rede, comunicação cifrada com o VNA central/nuvem |
| **SMooTH VNIN** | Comercial | Rede entre instituições: compartilha, armazena em cache e sincroniza estudos; *prefetch* de exames anteriores antes da chegada do paciente; distribuição automática de trabalho; IHE (HL7, DICOM, XDS, XCA) |

## 3. Estado real do VYONIX (resumo verificado no código)

* **Motor:** Orthanc sem plugins (GPLv3, ADR-0012); índice próprio por organização no PostgreSQL com RLS;
  DICOMweb STOW/QIDO/WADO-RS no Core; C-FIND/C-MOVE/C-GET, MWL e MPPS servidos pelo Core com nós autorizados.
* **Integridade:** SHA-256 na entrada e na saída; reenvio idempotente; recusa de conteúdo divergente; verificação
  contínua; backup diário verificado e restauração.
* **Borda/nuvem:** modo *edge* (um servidor por clínica) e modo *cloud* (multiorganização com rotas de AE Title e
  quarentena). Ainda **não há sincronização edge → cloud** de estudos.
* **Fluxo:** cadastro, pedidos, agenda, worklist, MPPS, Central de Exames, preparação técnica, distribuição,
  laudo com liberação por senha, PDF, FHIR/HL7/DICOM-PDF, Minha Produção, linha do tempo do exame.
* **Viewer:** OHIF 3.13 (MIT) na mesma origem, sem modificações.

## 4. Matriz comparativa

Prioridade: **A** = alto valor e baixo risco (fazer já) · **B** = valor alto, exige desenho/aprovação · **C** = depois.

| # | Funcionalidade | dcm4chee (aberto) | SMooTH (comercial, público) | VYONIX atual | Melhoria proposta | Prior. |
|---|---|---|---|---|---|---|
| 1 | Cadastro de dispositivos/AEs | Dispositivo + AEs + conexões em LDAP; AEs de origem aceitos por AE | Administração central (não detalhada) | **Feito hoje:** nós DICOM com fabricante, modelo, modalidade, unidade, IP/nome, porta, serviços permitidos, ativo, status | Importar/exportar cadastro (CSV) para implantação em massa | C |
| 2 | AE desconhecido | Configurável (aceitar/recusar AEs de origem) | — | **Feito hoje:** Q/R recusa e registra; C-STORE: política por instituição (aceitar todos × só cadastrados, com retenção sem exclusão) | Recusa já na associação do C-STORE (Orthanc `DicomAlwaysAllowStore=false` + modalidades sincronizadas pelo Core) — muda a configuração do motor instalada | B |
| 3 | Teste de conectividade | C-ECHO pela UI | — | **Feito hoje:** C-ECHO com tempo de resposta, último teste e erro | — | — |
| 4 | Histórico/erros de associação | Logs e auditoria ATNA | — | **Feito hoje:** histórico por organização (aceitas, recusadas com motivo, C-STORE, C-ECHO, C-MOVE recusado), agrupado | Exportar o histórico; alertas por e-mail | C |
| 5 | Regras de roteamento/exportação | *Export rules* por AE de origem, modalidade, atributos; fila com novas tentativas | Distribuição automática (VNIN) | **Feito hoje:** regras por origem e modalidade, envio manual, fila persistente com novas tentativas, SHA-256 conferido, histórico e auditoria | Encaminhar imagens que chegam depois do envio (complemento do estudo) | A (feito) |
| 6 | Storage Commitment | SCP e SCU (após exportação), só confirma após releitura com checksum | — | Não há (a integridade é por SHA-256 na entrada) | SCP de *storage commitment* no Core respondendo com base no índice + SHA-256 (sem mudar o motor) | B |
| 7 | Duplicados / atributos divergentes | Políticas configuráveis (sobrescrever, guardar, ignorar; complementar/substituir atributos) | — | Política fixa e conservadora: idêntico = idempotente; divergente = recusa | Manter (segurança); expor a recusa na tela de qualidade (já existe) | — |
| 8 | Rejeição/IOCM (KOS) | Notas de rejeição ocultam instâncias com retenção própria | — | Não há | Rejeição lógica de instâncias/séries pelo administrador, auditada, sem exclusão física | C |
| 9 | Retenção | Políticas por estudo, com exclusão automática | — | Relatório + guarda obrigatória; **sem exclusão** (exige política aprovada) | Manter; exclusão só após aprovação expressa | Aprovação |
| 10 | MWL / MPPS / UPS | MWL, MPPS, UPS | — | MWL e MPPS (com imagens e dose informadas); UPS não | UPS só se houver caso de uso (pós-processamento) | C |
| 11 | HL7 v2 (ADT/ORM/ORU) | Servidor HL7 MLLP | IHE HL7 | Exportação HL7 ORU do laudo; sem servidor MLLP de entrada | Receptor HL7 ADT/ORM (MLLP) para HIS externo | B |
| 12 | IHE XDS/XDS-I/XCA | XDS-I, integração com registros | XDS, XCA (VNIN) | FHIR (DiagnosticReport) e DICOM PDF; sem XDS | Avaliar necessidade com clientes antes de investir | C |
| 13 | Auditoria | ATNA (mensagens de auditoria IHE) | "Seguro e conforme" | Trilha própria encadeada, por organização | Exportação em formato ATNA (RFC 3881/DICOM PS3.15) para SIEM | C |
| 14 | Monitoramento | Filas, métricas, painéis | — | Estado de serviços, motor, Q/R, backup, integridade, licença | **Feito hoje:** espaço em disco com alerta (dados e armazenamento DICOM) | A |
| 15 | Viewer web | Integração com viewers externos | SMooTH Viewer zero-footprint, documentos | OHIF 3.13 zero-footprint, mesma origem, cookie da sessão | Exibir anexos/PDF do laudo ao lado (já no painel do estudo) | — |
| 16 | Exames anteriores (*prefetch*) | Pré-busca por regras (consultas a arquivos remotos) | *Prefetch* inteligente antes da chegada (VNIN) | Não havia lista de anteriores no laudo | **Feito hoje:** "exames anteriores" do mesmo paciente na preparação e no laudo (índice local). Pré-busca de PACS remoto (C-MOVE agendado) = item B | A (local) / B (remoto) |
| 17 | Operação local + nuvem | Arquivos em camadas, exportação | VNEdge: borda resiliente, cifrada, sincroniza com o central | Edge e cloud existem separados; sem sincronização | **Sincronização edge → cloud** (fila de envio STOW-RS com mTLS, retomada, SHA-256 conferido, sem apagar o local) — exige desenho (ADR) e aprovação | B |
| 18 | Alta disponibilidade | Cluster, ativo/ativo | Ativo/ativo, datacenters | Servidor único por clínica; backup verificado | Documentar RPO/RTO atuais; HA só no modo cloud (PostgreSQL replicado, motor com armazenamento compartilhado) | C |
| 19 | Multiorganização | Multiorganização por configuração | Redes regionais/nacionais | RLS por organização, rotas de AE, papéis por instituição, isolamento testado | Manter; testes de escala com muitas organizações | C |
| 20 | Fluxo configurável | — (arquivo) | Distribuição automática | **Feito hoje:** etapas configuráveis (agendamento, worklist), preparação obrigatória opcional, distribuição manual/fixa/equilibrada, linha do tempo do exame | Regras de distribuição por modalidade/unidade | B |
| 21 | Produção médica | — | — | **Feito hoje:** Minha Produção com permissões e exportação | Fechamento mensal aprovado pela coordenação | C |
| 22 | Segurança de transporte | DICOM TLS, HTTPS, Keycloak | Comunicação cifrada | HTTPS no Core; DICOM sem TLS (rede local) | DICOM TLS opcional no Q/R do Core (pynetdicom suporta) | B |

## 5. Oportunidades priorizadas para o VYONIX

**Implementadas neste ciclo (alto valor, baixo risco, compatíveis com o PACS atual):** itens 1–5, 14, 16 (local),
20 e 21 — ver `VYONIX_PROJECT_STATE.md`.

**Próximo ciclo técnico (sem decisão comercial, só desenho e testes):**
1. Complemento do encaminhamento: imagens recebidas depois do envio.
2. *Storage commitment* SCP no Core (item 6), respondendo pelo índice com SHA-256 — sem alterar o Orthanc.
3. Receptor HL7 ADT/ORM (item 11) para integrar HIS externo sem digitação dupla.
4. DICOM TLS opcional no Q/R (item 22).

**Exigem decisão/aprovação do responsável (registrar em ADR antes):**
* Recusa de C-STORE já na associação (item 2): altera a configuração do Orthanc instalada pelo DEPLOY.
* Sincronização edge → cloud (item 17): define onde ficam os dados clínicos e o contrato com a clínica (LGPD).
* Exclusão por retenção (item 9) e rejeição lógica IOCM (item 8).

## 6. O que não fazer

* Não reimplementar o dcm4chee nem trocar o motor Orthanc.
* Não copiar configurações LDAP, telas ou textos do dcm4chee/SMooTH.
* Não anunciar "VNA", "alta disponibilidade" ou "IHE XDS" enquanto não estiverem implementados e testados.
* Não alterar a instalação laboratorial do DICOM Print nem o comportamento homologado do BKL-10.
