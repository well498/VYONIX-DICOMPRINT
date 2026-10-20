# Guia de Configuração DICOM

**VYONIX DICOM Print {VERSION}**

> **Importante:** nesta versão (Fase 1) os serviços DICOM **ainda não estão implementados**. O VYONIX não aceita conexões, não responde a C-ECHO, não recebe imagens e não atua como impressora DICOM. Não configure equipamentos de produção para enviar ao VYONIX. Este guia descreve apenas os parâmetros que já podem ser definidos e validados, para que a implantação seja planejada com antecedência.

## 1. Parâmetros disponíveis

Menu **Configurações**:

| Parâmetro | Padrão | Observação |
|---|---|---|
| AE Title local (recepção) | `VYONIX` | Até 16 caracteres ASCII, sem barra invertida |
| Endereço IP de escuta | `0.0.0.0` | Todas as interfaces IPv4 |
| Porta TCP (recepção) | `11112` | Portas abaixo de 1024 exigem atenção a privilégios e firewall |
| Associações simultâneas (máx.) | `10` | De 1 a 64 |
| Aceitar equipamentos não cadastrados | Desativado | Recomendado apenas durante a implantação |
| Habilitar DICOM Print SCP | Desativado | Serviço previsto na Fase 5 |
| AE Title de impressão | `VYONIX_PRINT` | Deve ser diferente do AE Title de recepção |
| Porta TCP de impressão | `11113` | Deve ser diferente da porta de recepção |

## 2. Planejamento da implantação

Para cada equipamento que enviará imagens no futuro, levante:

| Informação | Exemplo |
|---|---|
| Nome e local | Tomógrafo — Sala 2 |
| Fabricante e modelo | (conforme etiqueta do equipamento) |
| Modalidade | CT, MR, CR, DX, US, MG... |
| AE Title do equipamento | `CT_SALA2` |
| Endereço IP do equipamento | `192.168.10.25` |
| Serviço usado | Envio de imagens (Storage) ou impressão DICOM (Print) |

No equipamento, o destino será configurado com o **AE Title**, o **IP do computador do VYONIX** e a **porta** definidos acima.

## 3. Como os serviços funcionarão (fases futuras)

- **Recepção (Storage SCP, Fase 2):** responderá a C-ECHO e receberá imagens por C-STORE apenas de equipamentos cadastrados e autorizados por AE Title e endereço IP.
- **Impressão DICOM (Print SCP, Fase 5):** receberá sessões de filme (Film Session, Film Box, Image Box) com os parâmetros de impressão enviados pelo equipamento.
- O envio de imagens por C-STORE **não** transmite instruções de impressão; nesses casos valerão as regras locais do VYONIX (Fase 6).

## 4. Declaração de conformidade DICOM

Ainda não existe declaração de conformidade DICOM para o VYONIX. Ela será publicada somente para os serviços efetivamente implementados e validados.
