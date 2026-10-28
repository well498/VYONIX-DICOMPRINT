# Declaração de Conformidade DICOM — VYONIX PACS (preliminar)

**VYONIX PACS 0.1.0** (módulo da Plataforma VYONIX) · motor DICOM: Orthanc 1.13.0 oficial, sem plugins

> **Preliminar, de desenvolvimento.** Descreve somente o que esta versão implementa e verifica em testes
> automatizados com dados DICOM sintéticos (PostgreSQL e Orthanc reais no CI, navegador Chromium para o Viewer).
> Não houve teste com modalidades, estações ou PACS reais. Não constitui declaração de adequação ao uso clínico
> nem de conformidade regulatória. Estrutura inspirada na PS3.2; seções sem implementação estão marcadas.

## 1. Visão geral

| Interface | Serviço | Papel | Implementado por | Verificação automatizada |
|---|---|---|---|---|
| DICOMweb (HTTPS) | STOW-RS (armazenar) | Origem e destino | Core VYONIX | `tests_platform/test_pacs.py` |
| DICOMweb (HTTPS) | QIDO-RS (pesquisar) | Origem | Core VYONIX | `test_pacs.py`; Viewer no Chromium |
| DICOMweb (HTTPS) | WADO-RS (recuperar instância, série, estudo, metadados, frames) | Origem | Core VYONIX | `test_pacs.py`; Viewer no Chromium |
| DIMSE (TCP) | Verification | SCP | Orthanc | `tests_platform/test_pacs_engine.py` |
| DIMSE (TCP) | Storage | SCP | Orthanc; indexação pelo Core (sincronização) | `test_pacs_orthanc.py` (C-STORE com pynetdicom) |
| DIMSE (TCP) | Verification; Study Root Q/R — FIND e MOVE | SCP (e SCU de Storage nas sub-operações do MOVE) | Core VYONIX (pynetdicom) | `tests_platform/test_pacs_qr.py` |
| DIMSE (TCP) | Modality Worklist — FIND | SCP | Core VYONIX (módulo RIS) | `tests_platform/test_ris.py` |

**Não implementado nesta versão:** C-GET, Patient Root e Patient/Study Only Q/R, consultas relacionais e
estendidas, MPPS, Storage Commitment, Instance Availability Notification, Storage SCU (envio a
outros sistemas), WADO-URI, UPS-RS, mídia removível (DICOMDIR) e STOW-RS de metadados com dados volumosos separados
(só objetos DICOM Part 10).

## 2. Arquitetura relevante para a conformidade

* O **Orthanc** guarda os arquivos e responde ao DIMSE. Ele não é exposto diretamente: a REST dele só aceita a
  própria máquina, com usuário e senha (ADR-0012).
* O **Core** mantém o índice por organização (PostgreSQL com row level security), implementa o DICOMweb, autoriza
  cada requisição pela sessão do usuário e audita entrada, recusa e abertura de estudos.
* Toda instância tem o SHA-256 registrado na entrada e conferido a cada recuperação; divergência é recusada.

## 3. DIMSE (Orthanc)

### 3.1 Entidade de aplicação

| AE | AE Title | Porta | Observação |
|---|---|---|---|
| Armazenamento | `VYONIX_PACS` | 4242 | Called AE conferido (`DicomCheckCalledAet`); porta aberta só para a rede local pelo DEPLOY |

### 3.2 Política de associação

* **C-ECHO:** aceito de qualquer Calling AE.
* **C-STORE:** aceito de qualquer Calling AE (`DicomAlwaysAllowStore`). Instâncias já existentes não são
  sobrescritas (`OverwriteInstances: false`).
* **C-FIND, C-MOVE, C-GET e consulta de worklist no motor:** recusados (`DicomAlwaysAllowFind/Move/Get/FindWorklist:
  false` e nenhuma modalidade cadastrada), porque passariam por fora da autorização e do isolamento do Core. A
  consulta/recuperação DIMSE é servida pelo Core (seção 3.4).
  Verificado no CI com o binário real: C-FIND de AE não cadastrado nunca devolve sucesso nem resultados.
* Classes SOP e sintaxes de transferência aceitas no C-STORE: as padrão do Orthanc 1.13.0 (consultar a documentação
  do Orthanc). O VYONIX não as altera.

### 3.3 Indexação do que chega por C-STORE

O serviço VyonixWorker consulta o registro de mudanças do motor a cada 15 s e indexa cada instância nova com as
mesmas validações do STOW-RS (seção 4.1):

* **Modo edge** (um servidor por organização): tudo vai para a organização do servidor, se o módulo PACS estiver
  habilitado e licenciado.
* **Modo cloud** (motor compartilhado): a instância vai para a organização dona do **AE Title chamado** pela
  modalidade (`CalledAET` registrado pelo motor). Cada organização reserva os seus AE Titles em *Rotas DICOM*
  (`/api/v1/pacs/routes`, permissão `pacs.admin`); um AE Title pertence a uma só organização no servidor.
  Instância sem rota, recebida por outro meio que não o DICOM, ou de organização sem módulo ou licença vigente fica
  em **quarentena**: não é indexada para ninguém e é contada no estado da sincronização. O motor do modo cloud
  precisa aceitar AE Titles diferentes do seu (`DicomCheckCalledAet: false`); a instalação do modo cloud ainda não é
  feita pelo DEPLOY. Instâncias recusadas na
indexação ficam no motor, mas **não** aparecem na pesquisa nem na recuperação e a recusa é auditada.

### 3.4 Consulta/recuperação pelo Core (C-FIND / C-MOVE)

| AE | AE Title | Porta | Classes SOP |
|---|---|---|---|
| Consulta/recuperação | `VYONIX_QR` (modo cloud: o AE Title roteado da organização) | 4243 (configurável: `pacs_qr_port`) | Verification `1.2.840.10008.1.1`; Study Root Q/R FIND `1.2.840.10008.5.1.4.1.2.2.1`; Study Root Q/R MOVE `1.2.840.10008.5.1.4.1.2.2.2` |

* **Associação:** aceita só de nós DICOM cadastrados pela organização com permissão de consultar (`/api/v1/pacs/nodes`,
  permissão `pacs.admin`); se o nó tiver IP cadastrado, o endereço precisa conferir. AE desconhecido, IP divergente,
  nó sem permissão de consultar ou AE chamado sem organização: associação recusada (calling/called AE not recognised).
* **C-FIND:** níveis STUDY (chaves: PatientID, PatientName, StudyDate, AccessionNumber, StudyInstanceUID,
  ModalitiesInStudy, StudyDescription — mesmas regras de curinga do QIDO-RS), SERIES (StudyInstanceUID obrigatório;
  Modality) e IMAGE (StudyInstanceUID; SeriesInstanceUID). Devolve os atributos pedidos e RetrieveAETitle.
* **C-MOVE:** níveis STUDY, SERIES e IMAGE, só para destinos da mesma organização cadastrados para receber (IP e
  porta); destino desconhecido: `0xA801`. Arquivos enviados na sintaxe de transferência original, sem recompressão,
  com o SHA-256 conferido (divergência: instância não enviada e contada como falha).
* **Auditoria:** cada consulta (nível, AE, quantidade — sem dados do paciente) e cada envio (destino, quantidades,
  falhas de integridade); o envio também registra a abertura do estudo (finalidade `dimse-move`).

### 3.5 Modality Worklist (módulo VYONIX RIS)

* Classe SOP: Modality Worklist Information Model – FIND `1.2.840.10008.5.1.4.31`, no mesmo AE e porta da seção 3.4,
  com a mesma autorização de nós DICOM.
* Exige o módulo RIS habilitado e com licença vigente na organização (trabalho novo); sem isso, a resposta é
  `0xC001` (impossível processar).
* Chaves de filtro: Modality, ScheduledStationAETitle e ScheduledProcedureStepStartDate (dia ou intervalo, no fuso
  da clínica) dentro de ScheduledProcedureStepSequence; PatientID, PatientName (prefixo), AccessionNumber.
* Atributos devolvidos (os pedidos): PatientName (Família^Nome), PatientID (identificador do emissor `DICOM`, se
  houver) e IssuerOfPatientID, PatientBirthDate, PatientSex, AccessionNumber, **StudyInstanceUID atribuído no
  agendamento** (raiz 2.25, derivada de UUID), RequestedProcedureID/Description/Priority, ReferringPhysicianName e a
  sequência do passo agendado (Modality, ScheduledStationAETitle, data, hora, descrição, SPS ID, ScheduledStationName e
  **ScheduledProcedureStepStatus** (0040,0020): `SCHEDULED`, `ARRIVED` após o check-in, `STARTED` em andamento).
* Só agendamentos "agendado", "paciente chegou" ou "em andamento". Quando o estudo com o UID agendado chega ao PACS, o agendamento passa a
  "recebido" e sai da worklist. Cada consulta é auditada (AE, quantidade; sem dados do paciente).
* MPPS não implementado.

## 4. DICOMweb (Core)

Base: `https://<servidor>:<porta>/api/v1/pacs/dicomweb`. Autenticação pela sessão do VYONIX (cookie
`HttpOnly`, `Secure`, `SameSite=Strict`); requisições que alteram dados exigem o cabeçalho `X-CSRF-Token`.

| Permissão | Recursos |
|---|---|
| `pacs.studies.store` | STOW-RS (também exige módulo habilitado e licença vigente) |
| `pacs.studies.read` | QIDO-RS, WADO-RS (não dependem de licença vigente: dados já armazenados continuam acessíveis) |

### 4.1 STOW-RS — `POST /studies` e `POST /studies/{StudyInstanceUID}`

* Corpo `multipart/related; type="application/dicom"` (RFC 2387) ou `application/dicom` (uma instância).
  Limite de 1 GB por requisição e de 2 GB por instância.
* Validação de cada instância: cabeçalho Part 10; Study, Series, SOP Instance e SOP Class UID presentes, com até
  64 caracteres e só dígitos e pontos; UIDs de estudo, série e instância distintos; Patient ID presente.
* Recusas: arquivo não DICOM ou corrompido; UID ausente ou inválido; Patient ID ausente; mesmo SOP Instance UID
  com conteúdo diferente; série já pertencente a outro estudo; Patient ID diferente do já indexado para o mesmo
  estudo; conteúdo diferente já guardado no motor com os mesmos identificadores; estudo diferente do indicado na URL.
* Reenvio do mesmo conteúdo: aceito sem duplicar (aviso `0xB007` na resposta).
* Resposta `application/dicom+json`: `00081199` (aceitas, com `00081190`), `00081198` (recusadas, com `00081197`
  Failure Reason: `0xC000` não compreendida, `0xA770` conflito com conteúdo já indexado, `0x0110` falha de
  processamento, `0xA900` estudo divergente da URL). HTTP 200 (todas aceitas), 202 (parcial), 409 (nenhuma).
  Motivos legíveis no cabeçalho `X-Vyonix-Failures` e na auditoria.

### 4.2 QIDO-RS

| Recurso | Chaves de pesquisa | Observações |
|---|---|---|
| `GET /studies` | `PatientID` (exato ou com `*`/`?`), `PatientName` (prefixo, sem distinção de maiúsculas, `*`/`?`), `StudyDate` (`AAAAMMDD` ou intervalo `AAAAMMDD-AAAAMMDD`), `AccessionNumber`, `StudyInstanceUID` (lista separada por vírgulas), `StudyDescription` (contém), `ModalitiesInStudy` (lista), `limit` (até 500), `offset` | `includefield` e `fuzzymatching` são aceitos e ignorados |
| `GET /studies/{uid}/series` | `Modality` | |
| `GET /studies/{uid}/instances`, `GET /studies/{uid}/series/{uid}/instances` | — | |

Atributos devolvidos — estudo: 00080020, 00080030, 00080050, 00080061, 00080090, 00081030, 00100010, 00100020,
00100030, 00100040, 0020000D, 00200010, 00201206, 00201208; série: 00080060, 0008103E, 0020000D, 0020000E,
00200011, 00201209; instância: 00080016, 00080018, 0020000D, 0020000E, 00200013, 00280008, 00280010, 00280011.
Sem resultados: HTTP 204. Ordem: data do estudo (mais recente primeiro).

### 4.3 WADO-RS

| Recurso | Resposta |
|---|---|
| `GET /studies/{uid}`, `/series/{uid}`, `/instances/{uid}` | `multipart/related; type="application/dicom"`, arquivos idênticos aos recebidos (SHA-256 conferido) |
| `GET /studies/{uid}/metadata`, `/series/{uid}/metadata` | `application/dicom+json` sem dados de pixel; `7FE00010` com `BulkDataURI` para os frames; `00083002` com a sintaxe original |
| `GET .../instances/{uid}/frames/{lista}` | Sem compressão: `application/octet-stream` em Explicit VR Little Endian. Comprimidos, sem recompressão: JPEG Baseline/Extended/Lossless (`image/jpeg`), JPEG-LS (`image/jls`), JPEG 2000 (`image/jp2`), RLE (`image/x-dicom-rle`) |

Não implementado: negociação pelo cabeçalho `Accept` (o formato acima é sempre usado), transcodificação,
renderização (`/rendered`, `/thumbnail`), Explicit VR Big Endian em frames.

## 5. Conjuntos de caracteres

Os arquivos são guardados e devolvidos como recebidos. O índice e o DICOM JSON usam a decodificação do pydicom
conforme o Specific Character Set do objeto.

## 6. Segurança e privacidade

* DICOMweb só por HTTPS, com sessão e permissões do VYONIX; isolamento por organização no banco.
* REST do motor só local, com senha guardada no cofre do Core; nenhum plugin carregado.
* Auditoria encadeada (SHA-256) de entrada, recusa e abertura de estudo (uma abertura por usuário e estudo a cada
  10 minutos). Eventos internos (`pacs.study.received.v1`) não levam dados do paciente.
* DIMSE sem TLS nesta versão (rede local da clínica); porta de consulta 4243 aberta só para a rede local pelo DEPLOY.

## 7. Pendências para a versão de homologação

C-GET; instalação do modo cloud;
MPPS (com o RIS); TLS no DIMSE; teste de interoperabilidade com modalidades e estações reais; revisão desta
declaração por especialista.
