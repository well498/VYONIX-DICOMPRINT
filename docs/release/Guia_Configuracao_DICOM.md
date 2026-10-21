# Guia de Configuração DICOM

**VYONIX DICOM Print {VERSION}**

> O software não está validado para uso clínico. A interoperabilidade com cada equipamento deve ser verificada na homologação (ver *Roteiro de Testes Manuais*).

## 1. Como funciona

O VYONIX é o **servidor DICOM receptor**. Cada equipamento é configurado para enviar ao **IP do computador VYONIX**, usando o **AE Title de destino** e a **porta** de uma **Regra DICOM**. A regra define o que acontece com o que chega: impressora, papel, orientação, layout, cópias, calibração (brilho, contraste, gama), cabeçalho e rodapé, e o modo de impressão (automática ou sob demanda).

**O IP do equipamento não é necessário.** A regra é escolhida por:

1. **porta de entrada** (listener) + **AE Title de destino** (*Called AE Title*) — critério principal;
2. **Calling AE Title** do equipamento — critério adicional **opcional**, para diferenciar regras com o mesmo destino;
3. **IP ou faixa de IP de origem** — **restrição opcional**.

A regra nunca é escolhida pela modalidade do exame. Duas regras com a mesma combinação não podem ser cadastradas; se uma ambiguidade surgir (ex.: cópia de banco), a conexão é recusada com o motivo — nunca resolvida em silêncio. Se o IP de um equipamento mudar, nada precisa ser editado (a não ser que a regra restrinja o IP).

> **Segurança:** AE Title e endereço IP **não são autenticação criptográfica**. Proteja a rede (VLAN dos equipamentos, Firewall do Windows). DICOM TLS não é oferecido nesta versão.

## 2. Servidor DICOM (configuração global)

*Configurações → DICOM — Recepção / Impressão* e *Servidor DICOM*:

| Parâmetro | Padrão | Observação |
|---|---|---|
| Endereço IP de escuta | `0.0.0.0` | Todas as interfaces IPv4; use um IP para escutar em uma só rede |
| Porta TCP de recepção (C-STORE) | `11112` | Evita a porta 104, que exige privilégios e costuma ter conflitos |
| Porta TCP de impressão (DICOM Print) | `11113` | Deve ser diferente da porta de recepção |
| AE Title padrão de recepção / impressão | `VYONIX` / `VYONIX_PRINT` | Usado quando uma regra não informa outro destino |
| Associações simultâneas | `10` | Por serviço |
| Aceitar destino padrão sem regra | Desligado | Ligado: envios ao AE padrão, na porta padrão, sem regra correspondente são aceitos com as configurações globais |

**Mais de uma porta:** uma regra pode ter **porta própria**; o VYONIX abre essa porta automaticamente (em até 10 segundos) e a fecha quando a regra é removida ou desabilitada. A mesma porta não pode servir aos dois serviços (C-STORE e DICOM Print).

A tela **Servidor DICOM** mostra o estado de cada serviço (em execução, parado, erro), as portas abertas, os **AE Titles de destino aceitos** (todas as regras), as associações ativas e os eventos recentes (aceites, recusas e motivos). O botão **Testar** faz um C-ECHO local.

## 3. Adicionar Regra DICOM

Menu **Regras DICOM → Adicionar Regra DICOM**:

| Campo | Exemplo | Uso |
|---|---|---|
| Nome da regra * | Tomografia 01 | Identificação |
| AE Title de destino * | `VYONIX_CT01` | O que o equipamento informa como AE Title do destino |
| Serviço DICOM | Recepção de imagens (C-STORE) | Ou Impressão DICOM (Print SCP) |
| Porta do VYONIX | padrão (11112) | Ou uma porta própria da regra |
| Impressora Windows, papel, orientação, layout, cópias | HP LaserJet, A4, automática, 2 × 2, 1 | Impressão desta regra |
| Brilho, contraste, gama | 0,0 (neutro) | −5 a +5, passo 0,5 (ajuste fino na Calibração de imagem) |
| Cabeçalho e rodapé BMP | ligados | `header.bmp` / `footer.bmp` universais |
| Modo de impressão | Automática ou Sob demanda | Sob demanda: aguarda a recepção (VYONIX Reception) |

**Restrições de origem — opcional (avançado):** Calling AE Title (vazio = qualquer equipamento) e IP ou faixa (`192.168.1.20`, `192.168.1.0/24` ou vários separados por vírgula; vazio = qualquer IP da rede). Combinações: qualquer origem; só Calling AE; só IP/faixa; Calling AE + IP. Associações fora das restrições são recusadas e registradas.

**Mesmo AE Title de destino em mais de uma regra:** permitido somente com critério explícito — Calling AE Titles diferentes (a regra com Calling AE definido tem precedência sobre a regra "qualquer origem") ou faixas de IP que não se sobrepõem.

Outras ações da lista: **Editar**, **Duplicar** (cópia independente, criada desabilitada, com novo AE Title de destino), **Habilitar / desabilitar**, **Importar / Exportar** (exportações da versão anterior são convertidas: destino = AE padrão), **Configurações de impressão…** (todos os parâmetros, inclusive margens), **Calibração de imagem…** (teste 3 × 3), **Regras avançadas da regra…** (condições por descrição, horário etc.) e **Histórico**.

## 4. Configurar destino no equipamento

Após salvar uma regra, a tela **Configurar destino no equipamento** mostra o que o técnico deve digitar na modalidade:

- Nome da regra: **Tomografia 01**
- AE Title de destino: **VYONIX_CT01**
- IP do servidor VYONIX: **192.168.1.100** — com várias placas de rede, é escolhido o IP da mesma rede do equipamento (pela faixa da regra ou pelo último IP visto); os demais são listados
- Porta: **11112**

Botões: **Copiar configuração**, **Testar conexão (C-ECHO)** (verifica porta + destino a partir deste computador), **Verificar porta ativa**, **Último equipamento conectado** e **Erros de associação** desta regra. Depois, faça o **Verify/Echo** no próprio equipamento.

## 5. Firewall do Windows

O instalador cria regras de entrada para `VyonixService.exe` e `Vyonix.exe` nas redes **privadas e de domínio** (portas DICOM e o VYONIX Reception, 8443). Redes públicas continuam bloqueadas. Por ser uma regra por programa, as portas próprias das regras ficam liberadas automaticamente.

## 6. C-STORE × DICOM Print

**Recepção C-STORE:** o equipamento envia objetos DICOM; o VYONIX grava cada imagem, agrupa por série e, quando a série fica sem novas imagens por *Configurações → Fila → agrupamento* (padrão alguns segundos), cria o trabalho. **O fim de uma associação, isoladamente, não conclui o exame.** O C-STORE não transporta parâmetros de impressão: valem os da regra.

**DICOM Print SCP:** o equipamento envia um filme (Film Session, Film Box, Image Box, N-ACTION). O VYONIX aceita Basic Grayscale e Basic Color Print Management, Presentation LUT e Printer (N-GET). Formatos `STANDARD\C,R` de 1×1 a 8×8. Só confirma a impressão ao equipamento depois de gravar as imagens e criar o trabalho. O pedido do filme (layout, orientação, cópias) é combinado com a regra conforme a política (*regra prevalece*, *pedido prevalece* ou *ignorar o pedido*). Compatibilidade: equipamentos configurados na versão anterior, que imprimem no AE padrão `VYONIX_PRINT`, continuam identificados pelo Calling AE da regra de recepção correspondente.

| Status devolvido (Print) | Quando |
|---|---|
| 0x0000 | Operação aceita |
| 0x0106 | Formato não suportado (ROW, COL, SLIDE, CUSTOM), orientação inválida ou Pixel Data inválido |
| 0x0112 | Film Session, Film Box ou Image Box inexistente |
| 0x0118 | Classe não suportada (ex.: Annotation Box) |
| 0x0123 | Ação diferente de "imprimir" |
| 0xB602 / 0xB603 | Pedido sem nenhuma imagem (nada é impresso) |

## 7. O que o VYONIX aceita (C-STORE)

**Classes de imagem (24):** CR; DX; MG (inclui tomossíntese); CT e Enhanced CT; MR e Enhanced MR; US e US multiframe; captura secundária; XA e Enhanced XA; RF e Enhanced RF; NM; PET e Enhanced PET.

**Sintaxes de transferência:** Implicit/Explicit VR Little Endian, Deflated, Explicit VR Big Endian; RLE Lossless, JPEG Baseline, JPEG 2000 e JPEG-LS (com e sem perdas). JPEG Lossless e JPEG Extended (12 bits) não são aceitos.

## 8. Armazenamento e retenção

- Gravação atômica em `C:\ProgramData\VYONIX\DICOM Print\storage\<estudo>\<série>\<instância>.dcm`; o arquivo original nunca é alterado; a confirmação ao equipamento só depois de gravar.
- Duplicata idêntica: confirmada e descartada; mesmo UID com conteúdo diferente: original mantido e alerta.
- Os dados de identificação do exame (nome, ID do paciente, Accession Number, atendimento) ficam disponíveis no VYONIX Reception e são apagados com as imagens no prazo de retenção (padrão 30 dias).

## 9. Diagnóstico

| Situação (Histórico / Servidor DICOM) | Causa provável |
|---|---|
| "AE Title de destino '…' não configurado na porta …" | O equipamento usa um AE Title de destino ou porta sem regra |
| "Calling AE '…' não autorizado para o destino …" | A regra restringe o Calling AE Title |
| "IP de origem … fora da restrição da regra" | O equipamento está fora da faixa permitida |
| "Regras ambíguas …" | Duas regras iguais: diferencie pelo Calling AE Title |
| "Regra … desabilitada" | Habilite a regra |
| "Recepção … recusada: funções suspensas pela licença" | Ative a licença ou a demonstração |
| Serviço em "Erro: a porta já está em uso" | Outro programa DICOM usa a porta; troque a porta |
| Nada aparece no Histórico | Firewall, rede, IP ou porta errados no equipamento |
