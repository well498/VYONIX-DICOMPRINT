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

**Não implementado nesta versão:** Query/Retrieve DIMSE (C-FIND, C-MOVE, C-GET — desligados explicitamente no motor,
ver 3.2), Modality Worklist, MPPS, Storage Commitment, Instance Availability Notification, Storage SCU (envio a
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
* **C-FIND, C-MOVE, C-GET e consulta de worklist:** recusados (`DicomAlwaysAllowFind/Move/Get/FindWorklist: false`
  e nenhuma modalidade cadastrada), porque passariam por fora da autorização e do isolamento do Core.
  Verificado no CI com o binário real: C-FIND de AE não cadastrado nunca devolve sucesso nem resultados.
* Classes SOP e sintaxes de transferência aceitas no C-STORE: as padrão do Orthanc 1.13.0 (consultar a documentação
  do Orthanc). O VYONIX não as altera.

### 3.3 Indexação do que chega por C-STORE

O serviço VyonixWorker consulta o registro de mudanças do motor a cada 15 s (modo edge, módulo habilitado e
licenciado) e indexa cada instância nova com as mesmas validações do STOW-RS (seção 4.1). Instâncias recusadas na
indexação ficam no motor, mas **não** aparecem na pesquisa nem na recuperação e a recusa é auditada.

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
* DIMSE sem TLS nesta versão (rede local da clínica).

## 7. Pendências para a versão de homologação

C-FIND/C-MOVE pelo Core com autorização; roteamento de C-STORE por AE Title no modo cloud; Modality Worklist e
MPPS (com o RIS); TLS no DIMSE; teste de interoperabilidade com modalidades e estações reais; revisão desta
declaração por especialista.
