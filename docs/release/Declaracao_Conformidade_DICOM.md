# Declaração de Conformidade DICOM

**VYONIX DICOM Print {VERSION}** · compilação {BUILD_DATE}

> **Versão de homologação.** Esta declaração descreve somente o que esta versão implementa e verifica em testes automatizados com um equipamento simulado (pynetdicom). Ela não substitui a verificação de interoperabilidade com os equipamentos reais de cada instalação e não constitui declaração de adequação ao uso clínico.

## 1. Visão geral

| Serviço | Papel | SOP Class |
|---|---|---|
| Verification | SCP | Verification `1.2.840.10008.1.1` |
| Storage | SCP | 24 classes de imagem (seção 3) |
| Print Management | SCP | Basic Grayscale Print Management Meta `1.2.840.10008.5.1.1.9` |
| Print Management | SCP | Basic Color Print Management Meta `1.2.840.10008.5.1.1.18` (opcional) |
| Print Management | SCP | Presentation LUT `1.2.840.10008.5.1.1.23` |
| Verification | SCU | apenas para o teste de conexão (C-ECHO) iniciado pelo usuário |

O VYONIX não implementa Query/Retrieve, Storage Commitment, Modality Worklist, MPPS, nem atua como Storage SCU (não envia imagens a outros sistemas).

## 2. Entidades de aplicação e rede

| AE | AE Title padrão (cada Regra DICOM define o seu AE Title de destino) | Porta padrão (regras podem ter porta própria) | Associações simultâneas |
|---|---|---|---|
| Recepção (Storage SCP) | `VYONIX` | 11112 | 10 (configurável, 1–64) |
| Impressão (Print SCP) | `VYONIX_PRINT` | 11113 | mesmo limite |

- Protocolo: DICOM Upper Layer sobre TCP/IP (IPv4). Endereço de escuta configurável (padrão 0.0.0.0).
- Tempo limite: ACSE 30 s; DIMSE e rede 60 s (recepção) e 120 s (impressão).
- PDU máximo: padrão do pynetdicom (16 382 bytes de recepção; o equipamento pode negociar outro valor).
- Nome da implementação e Implementation Class UID: os do pynetdicom.

### Política de associação

Cada serviço escuta na porta padrão e nas portas próprias das **Regras DICOM**. A regra é escolhida pela **porta de entrada + Called AE Title**:

1. Sem regra para a porta + Called AE Title: recusa *called AE title not recognised* (0x07), salvo se a opção *aceitar o destino padrão sem regra* estiver ligada e o destino for o AE padrão na porta padrão.
2. Calling AE Title fora da restrição opcional da regra: recusa *calling AE title not recognised* (0x03). Uma regra com Calling AE definido prevalece sobre a regra "qualquer origem" do mesmo destino.
3. Endereço IP fora da restrição opcional (IP ou faixa CIDR) da regra: recusa 0x03.
4. Regra desabilitada ou ambiguidade entre regras: recusa com o motivo registrado (nunca resolvida em silêncio).
5. Sem licença válida ou demonstração ativa: recusa transitória (*rejected-transient*), o equipamento pode tentar depois.

O IP do equipamento não é necessário para a configuração básica. AE Title e IP não constituem autenticação.
4. Recusas são permanentes (*rejected-permanent*, fonte *service-user*) e registradas no Histórico.

## 3. Storage SCP

### Classes de imagem aceitas

| SOP Class | UID | Papel |
|---|---|---|
| Computed Radiography Image Storage (CR) | `1.2.840.10008.5.1.4.1.1.1` | SCP |
| Digital X-Ray Image Storage - For Presentation (DX) | `1.2.840.10008.5.1.4.1.1.1.1` | SCP |
| Digital X-Ray Image Storage - For Processing (DX) | `1.2.840.10008.5.1.4.1.1.1.1.1` | SCP |
| Digital Mammography X-Ray Image Storage - For Presentation (MG) | `1.2.840.10008.5.1.4.1.1.1.2` | SCP |
| Digital Mammography X-Ray Image Storage - For Processing (MG) | `1.2.840.10008.5.1.4.1.1.1.2.1` | SCP |
| CT Image Storage (CT) | `1.2.840.10008.5.1.4.1.1.2` | SCP |
| Enhanced CT Image Storage (CT) | `1.2.840.10008.5.1.4.1.1.2.1` | SCP |
| Ultrasound Multi-frame Image Storage (US) | `1.2.840.10008.5.1.4.1.1.3.1` | SCP |
| MR Image Storage (MR) | `1.2.840.10008.5.1.4.1.1.4` | SCP |
| Enhanced MR Image Storage (MR) | `1.2.840.10008.5.1.4.1.1.4.1` | SCP |
| Ultrasound Image Storage (US) | `1.2.840.10008.5.1.4.1.1.6.1` | SCP |
| Secondary Capture Image Storage (OT) | `1.2.840.10008.5.1.4.1.1.7` | SCP |
| Multi-frame Single Bit Secondary Capture Image Storage | `1.2.840.10008.5.1.4.1.1.7.1` | SCP |
| Multi-frame Grayscale Byte Secondary Capture Image Storage | `1.2.840.10008.5.1.4.1.1.7.2` | SCP |
| Multi-frame Grayscale Word Secondary Capture Image Storage | `1.2.840.10008.5.1.4.1.1.7.3` | SCP |
| Multi-frame True Color Secondary Capture Image Storage | `1.2.840.10008.5.1.4.1.1.7.4` | SCP |
| X-Ray Angiographic Image Storage (XA) | `1.2.840.10008.5.1.4.1.1.12.1` | SCP |
| Enhanced XA Image Storage (XA) | `1.2.840.10008.5.1.4.1.1.12.1.1` | SCP |
| X-Ray Radiofluoroscopic Image Storage (RF) | `1.2.840.10008.5.1.4.1.1.12.2` | SCP |
| Enhanced XRF Image Storage (RF) | `1.2.840.10008.5.1.4.1.1.12.2.1` | SCP |
| Breast Tomosynthesis Image Storage (MG) | `1.2.840.10008.5.1.4.1.1.13.1.3` | SCP |
| Nuclear Medicine Image Storage (NM) | `1.2.840.10008.5.1.4.1.1.20` | SCP |
| Positron Emission Tomography Image Storage (PT) | `1.2.840.10008.5.1.4.1.1.128` | SCP |
| Enhanced PET Image Storage (PT) | `1.2.840.10008.5.1.4.1.1.130` | SCP |

### Sintaxes de transferência aceitas

| Sintaxe | UID |
|---|---|
| Implicit VR Little Endian | `1.2.840.10008.1.2` |
| Explicit VR Little Endian | `1.2.840.10008.1.2.1` |
| Deflated Explicit VR Little Endian | `1.2.840.10008.1.2.1.99` |
| Explicit VR Big Endian | `1.2.840.10008.1.2.2` |
| RLE Lossless | `1.2.840.10008.1.2.5` |
| JPEG Baseline (Process 1) | `1.2.840.10008.1.2.4.50` |
| JPEG-LS Lossless e Near-Lossless | `1.2.840.10008.1.2.4.80`, `1.2.840.10008.1.2.4.81` |
| JPEG 2000 (Lossless e com perdas) | `1.2.840.10008.1.2.4.90`, `1.2.840.10008.1.2.4.91` |

As sintaxes comprimidas só são oferecidas quando o decodificador correspondente está presente no pacote (verificado no autoteste). **Não** são aceitas: JPEG Extended (Process 2 & 4) e JPEG Lossless (Process 14). Quando o equipamento propõe várias sintaxes, a não comprimida é preferida.

### Comportamento do C-STORE

| Situação | Status |
|---|---|
| Imagem gravada (arquivo e banco) — só então a resposta é enviada | 0x0000 |
| Duplicata idêntica (mesmo SOP Instance UID e conteúdo) | 0x0000, descartada |
| Mesmo UID com conteúdo diferente | 0x0000; original mantido, alerta registrado |
| Imagem maior que o limite configurado / falha de disco | 0xA700 |
| Atributos obrigatórios ausentes ou UIDs inválidos | 0xA900 |
| Falha de processamento | 0xC000 / 0x0110 |

O arquivo original é gravado sem alteração. O C-STORE não transporta configurações de impressão; a impressão automática usa perfis, regras e padrões do VYONIX.

## 4. Print SCP

### Objetos e operações

| SOP Class | Operações | Observações |
|---|---|---|
| Basic Film Session | N-CREATE, N-SET, N-ACTION (imprimir), N-DELETE | Uma por associação; Number of Copies 1–99; Print Priority |
| Basic Film Box | N-CREATE, N-SET, N-ACTION (imprimir), N-DELETE | Image Display Format `STANDARD\C,R` de 1 × 1 a 8 × 8 |
| Basic Grayscale Image Box | N-SET | 8 ou 16 bits (Bits Stored ≤ 16), MONOCHROME1/2, Polarity NORMAL/REVERSE |
| Basic Color Image Box | N-SET | RGB 8 bits, Planar Configuration 0 ou 1 |
| Presentation LUT | N-CREATE, N-DELETE | IDENTITY, LIN OD e LUT explícita |
| Printer | N-GET | Printer Status NORMAL/WARNING/FAILURE conforme a impressora e a fila |

**Não suportados:** formatos ROW, COL, SLIDE, SUPERSLIDE e CUSTOM (0x0106); Basic Annotation Box, Image Overlay Box e Print Job SOP Class (0x0118); N-EVENT-REPORT; ações diferentes de *imprimir* (0x0123). O N-ACTION não devolve *Referenced Print Job Sequence*.

### Comportamento

- A resposta de sucesso do N-ACTION só é enviada depois que as imagens dos Image Boxes foram gravadas (como Secondary Capture) e o trabalho entrou na fila persistente.
- Pedido de impressão sem imagens: aviso 0xB602 (Film Session) ou 0xB603 (Film Box), nada é impresso.
- Repetir o N-ACTION do mesmo Film Box não gera nova impressão.
- Atributos respeitados: formato (layout com células vazias em branco), Film Orientation, Number of Copies, Print Priority, Polarity, Presentation LUT, Trim.
- Film Size ID: A4 e A3 viram papel; tamanhos de filme usam o papel do perfil/padrão, com anotação no trabalho.
- Magnification Type, Smoothing Type, Min/Max Density, Border Density e Empty Image Density são registrados e não alteram a impressão (densidades podem ser aplicadas por configuração).
- Atributos de texto livre (como Film Session Label) não são gravados no banco.

## 5. Conjuntos de caracteres

Character Set padrão (ISO-IR 6) e os conjuntos suportados pelo pydicom para leitura. O VYONIX não exibe nem imprime dados demográficos do paciente, exceto quando a opção *Nome e ID do paciente no cabeçalho* está ligada (desligada por padrão).

## 6. Segurança

Sem TLS (DICOM sobre TCP simples). O controle de acesso é feito pela política de associação (seção 2) e pelo firewall do Windows. Recomenda-se uso em rede interna segregada.
