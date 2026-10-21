# Guia de Configuração DICOM

**VYONIX DICOM Print {VERSION}**

> Este guia cobre a recepção de imagens (Storage SCP), disponível nesta versão. A impressão DICOM (Print SCP) ainda não está implementada. O software não está validado para uso clínico.

## 1. Visão geral

O VYONIX recebe imagens dos equipamentos por **C-STORE** e responde a **C-ECHO** (teste de conexão). Uma conexão só é aceita quando:

1. o equipamento chama o **AE Title do VYONIX** (configurado em Configurações);
2. o **AE Title do equipamento** está cadastrado, ativo e **autorizado** em Equipamentos DICOM;
3. se o equipamento tiver **IP cadastrado**, a conexão vem desse IP.

Conexões fora dessas regras são recusadas com o código DICOM apropriado e registradas no Histórico (categoria Segurança).

## 2. Configurar o VYONIX

Menu **Configurações → DICOM — Recepção (Storage SCP)**:

| Parâmetro | Padrão | Observação |
|---|---|---|
| AE Title local | `VYONIX` | Até 16 caracteres ASCII, sem barra invertida |
| Endereço IP de escuta | `0.0.0.0` | Todas as interfaces IPv4; use um IP específico para restringir |
| Porta TCP | `11112` | Portas abaixo de 1024 (ex.: 104) exigem privilégios e regra de firewall |
| Associações simultâneas (máx.) | `10` | Excedentes recebem "limite local excedido" |
| Iniciar a recepção automaticamente | Ligado | Inicia o servidor quando o VYONIX abre |
| Tamanho máximo por imagem | `1024 MB` | Imagens maiores são recusadas (status 0xA700) |
| Aceitar equipamentos não cadastrados | Desligado | Use só durante a implantação |

Ao salvar uma mudança de AE Title, endereço, porta ou limite, o servidor é reiniciado automaticamente.

> **Importante nesta versão:** o servidor DICOM funciona enquanto o VYONIX estiver aberto. A operação em segundo plano, como serviço do Windows, está prevista para a Fase 7.

## 3. Firewall do Windows

O instalador oferece a opção **"Permitir que equipamentos DICOM se conectem ao VYONIX"**, marcada por padrão. Ela cria uma regra de entrada para o `Vyonix.exe` nas redes **privadas e de domínio**. Redes públicas continuam bloqueadas. A regra é removida na desinstalação.

Se a opção foi desmarcada, crie a regra manualmente (Prompt de Comando como administrador):

```
netsh advfirewall firewall add rule name="VYONIX DICOM Print" dir=in action=allow program="C:\Program Files\VYONIX\DICOM Print\Vyonix.exe" enable=yes profile=private,domain
```

## 4. Cadastrar um equipamento

Menu **Equipamentos DICOM → Adicionar**:

| Campo | Exemplo | Uso |
|---|---|---|
| Nome * | Tomógrafo — Sala 2 | Identificação no VYONIX |
| AE Title * | `CT_SALA2` | Deve ser exatamente o AE Title configurado no equipamento |
| Modalidade | CT | Usada nos filtros e, futuramente, nas regras de impressão |
| Endereço IP | `192.168.10.25` | Se preenchido, só conexões deste IP são aceitas |
| Porta | `104` | Porta do equipamento, usada só no teste C-ECHO feito pelo VYONIX |
| Unidade, setor, fabricante, modelo, observações | — | Informativos |

Marque **Autorizado a enviar imagens** para liberar o equipamento. Um equipamento pode ser bloqueado a qualquer momento (**Autorizar / bloquear**) sem perder o cadastro.

Use **Testar conexão (C-ECHO)** para verificar se o VYONIX alcança o equipamento. O teste usa o AE Title local do VYONIX como chamador.

## 5. Configurar o equipamento

No equipamento (ou no seu sistema de envio), cadastre um destino DICOM com:

- **AE Title:** o AE Title local do VYONIX (padrão `VYONIX`);
- **Endereço IP:** o IP do computador do VYONIX;
- **Porta:** a porta configurada (padrão `11112`).

Depois, use o "Verify/Echo" do equipamento: no VYONIX, a coluna "Último contato" é atualizada e o evento aparece em **Servidor DICOM → Eventos DICOM recentes**.

## 6. O que o VYONIX aceita

**Classes de imagem (24):** CR; DX (apresentação e processamento); MG (apresentação, processamento e tomossíntese); CT e Enhanced CT; MR e Enhanced MR; US e US multiframe; captura secundária (simples e multiframe); XA e Enhanced XA; RF e Enhanced RF; NM; PET e Enhanced PET.

**Sintaxes de transferência:** Implicit VR Little Endian, Explicit VR Little Endian, Deflated Explicit VR Little Endian e Explicit VR Big Endian. Comprimidas: RLE Lossless, JPEG Baseline (8 bits), JPEG 2000 (com e sem perdas) e JPEG-LS (com e sem perdas). JPEG Lossless e JPEG Extended (12 bits) ainda não são aceitos. Quando o equipamento oferece sem compressão e comprimido, o VYONIX escolhe sem compressão.

## 7. Armazenamento

- Cada imagem é gravada primeiro em uma pasta temporária e só então movida para `C:\ProgramData\VYONIX\DICOM Print\storage\<estudo>\<série>\<instância>.dcm`. O arquivo original nunca é alterado.
- A confirmação ao equipamento (status 0x0000) só é enviada depois que a imagem está gravada no disco e registrada no banco.
- **Duplicatas:** uma imagem reenviada com o mesmo conteúdo é confirmada e descartada. Uma imagem com o mesmo identificador e conteúdo diferente mantém a original e gera um alerta.
- **Retenção:** imagens são removidas após o prazo de *Configurações → Retenção de dados* (padrão 30 dias), exceto as ligadas a trabalhos ainda não concluídos. PDFs gerados seguem o mesmo prazo.
- **Impressão automática:** cada série recebida vira um trabalho de impressão (desligável em *Configurações → Fila de impressão*). O C-STORE não transporta configurações de impressão: papel, layout e impressora vêm dos perfis e dos padrões do VYONIX.

## 8. Diagnóstico

| Situação | Onde ver | Causa provável |
|---|---|---|
| "Associação recusada: AE não cadastrado" | Histórico / Servidor DICOM | AE Title do equipamento diferente do cadastrado |
| "Called AE diferente do AE local" | Histórico | Destino configurado no equipamento com outro AE Title |
| "IP de origem diferente do cadastrado" | Histórico | Equipamento mudou de IP ou o cadastro está errado |
| "Equipamento bloqueado" | Histórico | Cadastro com autorização desligada |
| Servidor em "Erro: a porta já está em uso" | Servidor DICOM | Outro programa DICOM usa a porta; troque a porta |
| Equipamento não conecta e nada aparece no Histórico | — | Firewall, rede ou IP/porta errados no equipamento |

O botão **Testar (C-ECHO local)** em *Servidor DICOM* verifica o próprio servidor a partir deste computador.

## 9. Declaração de conformidade

A declaração de conformidade DICOM será publicada ao fim do desenvolvimento, restrita aos serviços efetivamente implementados e validados.
