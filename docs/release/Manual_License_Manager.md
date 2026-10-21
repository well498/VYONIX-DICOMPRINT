# Manual do VYONIX License Manager

**VYONIX License Manager {LM_VERSION}** · aplicativo administrativo de emissão de licenças do VYONIX DICOM Print {VERSION}

> **Uso exclusivo do fornecedor/administrador. Não distribua este programa, seu banco de dados, os backups ou as chaves aos clientes.**

## 1. Formas de uso

| Modo | Arquivo | Dados |
|---|---|---|
| **Portátil** (obrigatório) | `VYONIX_License_Manager.exe` — duplo clique, sem Python, sem o VYONIX DICOM Print, sem instalador | pasta `VYONIX_License_Manager_Dados` ao lado do executável (pen drive ou pasta protegida). Se a pasta não for gravável: `%APPDATA%\VYONIX\License Manager` |
| **Instalado** (opcional) | `VYONIX_License_Manager_Setup.exe` — instala o mesmo executável em Arquivos de Programas, com atalho | `%APPDATA%\VYONIX\License Manager` do usuário |

As funções são as mesmas nos dois modos. O banco é próprio (`license_manager.db`) e independente do banco do VYONIX DICOM Print. A desinstalação não apaga os dados. Requisito: Windows 10/11 64 bits.

## 2. Primeira execução

1. Crie o **usuário administrador** (senha com pelo menos 10 caracteres, misturando maiúsculas, minúsculas e números).
2. Em **Segurança → Chaves de emissão**, importe a chave oficial do produto (**Importar chave (.pem cifrado)…**, com o identificador `vyx-2026-01` e a frase-senha) **ou** gere uma nova chave.

Somente licenças assinadas por uma chave cuja parte pública está embutida no VYONIX DICOM Print são aceitas pelos clientes. A versão {VERSION} aceita a chave `vyx-2026-01` (impressão digital `44DE:3181:0922:95DC:C478:0FDC`). Uma chave gerada agora só passa a valer depois da rotação (seção 9).

## 3. Segurança

- **Usuários e papéis:** *Administrador comercial* (tudo), *Operador financeiro* (Gestão Comercial: pagamentos, carência, suspensão e reativação), *Suporte técnico* (reativação por troca de hardware, revalidação, autorizações offline), *Emissor* (clientes, solicitações, emissão, renovação, reativação, revalidação) e *Consulta* (somente leitura). Senhas guardadas com scrypt; bloqueio de 15 minutos após 5 tentativas erradas; senha provisória obriga a troca; a sessão é bloqueada após 15 minutos sem uso.
- **Chave privada:** Ed25519, guardada **somente cifrada** (PKCS#8 com a frase-senha) no banco. Para emitir, a chave é desbloqueada com a frase-senha e fica na memória por 15 minutos (**Bloquear agora** encerra antes). Nenhuma chave é embutida no executável (verificado no autoteste e no pipeline de compilação).
- **Backup protegido da chave:** Segurança → **Backup protegido da chave…** grava o PEM cifrado; guarde a frase-senha separada do arquivo, fora deste computador.
- **Auditoria:** todas as operações (acessos, emissões, reativações, revogações, chaves, usuários, backups) ficam registradas em cadeia — cada registro contém o resumo do anterior. **Histórico e auditoria → Verificar integridade** aponta registros alterados fora do aplicativo.

## 4. Fluxo de ativação offline

1. O cliente instala o VYONIX DICOM Print; o programa gera o Hardware ID e o Installation ID.
2. O cliente exporta a solicitação (`.vyreq` ou código `VYXR2-…`) e envia ao administrador.
3. **Solicitações e emissão → Importar solicitação e emitir licença…**. A tela mostra Hardware ID, Installation ID, unidade, versão, motivo, a situação do **TPM** ("assinada pelo TPM — prova verificada", "sem TPM" ou **assinatura inválida**) e o **histórico deste computador** (licenças anteriores com componentes em comum).
4. Selecione ou cadastre o **cliente**, escolha **tipo**, **edição**, **data de início**, **vencimento** (personalizada), **equipamentos** e **impressoras autorizados** (0 = sem limite), **recursos** e observações internas.
5. **Emitir e exportar licença assinada** grava `VYX-AAAA-XXXXXXXX.vylic`. Envie ao cliente, que a importa em Licença → Ativar licença comercial.

Tipos: **DEMO — 5 dias** (120 h a partir da ativação no computador, a ativar em até 30 dias; bloqueada para computadores que já receberam DEMO, salvo justificativa registrada), **Mensal**, **Trimestral**, **Semestral**, **Anual** (vencem às 23:59:59, horário de Brasília, da véspera do mesmo dia no mês final), **Permanente** (sem vencimento comercial; continua vinculada ao hardware, à instalação e à assinatura) e **Personalizada** (data escolhida).

Uma instalação com licença comercial ativa não recebe outra "nova": use **Renovar** (mesma instalação) ou **Reativar** (outra instalação ou computador).

## 4A. Gestão Comercial

A página **Gestão Comercial** mostra cada assinatura (cliente, CNPJ, instalação, plano, mensalidade, vencimento, último pagamento confirmado, dias de atraso, situação, último contato) com histórico, notificações, suspensões, reativações, pagamentos, cobranças e autorizações. Ações: registrar pagamento confirmado, comprovante (não quita), conceder carência, programar/cancelar suspensão, suspender conforme a política, reativar, exportar autorização offline (`.vyauth`), renovar, reemitir, plano e valor, publicar licença no License Server e auditoria. Na emissão, escolha **Validação: Offline/Online** e o valor. As regras completas estão em *Licenciamento Comercial por Assinatura*.

## 5. Renovação

**Licenças → Renovar…** emite uma nova licença para a mesma instalação e computador. Na renovação antecipada, o novo período começa no fim do período atual (o cliente não perde dias). A licença anterior fica como "substituída (renovada)".

## 6. REATIVAR / EMITIR NOVA LICENÇA

Para substituição de HD, troca de placa-mãe, substituição do computador, reinstalação do Windows, desinstalação e reinstalação do VYONIX, falha de armazenamento ou recuperação de sistema:

1. Selecione a licença anterior em **Licenças** e clique em **REATIVAR / EMITIR NOVA LICENÇA…**.
2. Consulte o **histórico do cliente** (instalações e reemissões).
3. Importe a **nova solicitação** do computador.
4. Escolha o **motivo** e descreva o ocorrido (obrigatório).
5. Por padrão o vencimento contratado é mantido.

A nova licença registra a licença anterior (`reissue_of`); a anterior fica "substituída (reativação)"; o histórico de reativações e de instalações do cliente é mantido. A reativação é sempre uma operação administrativa — o cliente não consegue se reativar sozinho.

## 7. Revogação

**Licenças → Revogar…** (somente administrador, com motivo). Como o produto é offline, a revogação só chega ao computador do cliente pela **lista de revogação assinada**: **Gerar lista de revogação…** grava `VYONIX-revogacao-N.vyrevoke`, que o cliente importa em Licença → Importar lista de revogação. Sem a lista, a licença continua valendo até o vencimento.

## 8. Revalidação de data/hora e de integridade

Quando o VYONIX suspende as funções por data/hora inconsistente ou registros de ativação alterados, o cliente exporta o **diagnóstico**. Em **Revalidação**, abra o arquivo: são exibidos o relógio do computador, o horário confiável, o problema detectado, as alterações de integridade e o histórico temporal. Se a situação for legítima (ex.: bateria da BIOS trocada), informe o motivo e emita a revalidação (`.vyreval`): ela redefine o horário confiável (e, se marcado, aceita o estado atual dos registros). Cada revalidação vale uma única vez, só para aquele diagnóstico, e **não devolve** tempo de licença ou de DEMO.

## 9. Rotação de chaves

1. Segurança → **Gerar nova chave…** (fica como *reserva*).
2. **Exportar chave pública…** copia a linha no formato de `app/licensing/keys.py` do VYONIX DICOM Print.
3. A nova chave pública é incluída no produto e distribuída em uma **atualização oficial**. Mantenha a chave antiga na lista para que as licenças existentes continuem válidas.
4. Depois que os clientes atualizarem, **Tornar ativa** a nova chave; a anterior pode ser *aposentada* (não emite mais; licenças já emitidas continuam válidas enquanto a chave pública constar do produto).

## 10. Clientes e LGPD

Cadastre apenas os dados necessários ao contrato (nome/razão social, CNPJ/CPF, responsável, contato, cidade/UF). A licença leva somente o nome do cliente. **Anonimizar (LGPD)** remove definitivamente os dados pessoais e mantém o histórico técnico das licenças sem identificação.

## 11. Backup, restauração e falhas do banco

- **Backup protegido** (`.vylmbak`): banco inteiro (clientes, licenças, chaves cifradas, auditoria) cifrado com AES-256-GCM e chave derivada da frase-senha (scrypt). Alterações no arquivo são detectadas.
- **Restaurar backup**: verifica a frase-senha, a integridade e a versão do banco; guarda o banco atual na pasta de backups antes da troca.
- **Cópias automáticas** diárias (10 mais recentes) na pasta `backups\automaticos` dos dados.
- **Banco danificado:** ao abrir, o License Manager detecta o problema e oferece restaurar a última cópia automática (o arquivo danificado é preservado com a extensão `.danificado`); sem cópia, restaure um backup protegido.

## 12. Linha de comando

`VYONIX_License_Manager.exe --self-test --report resultado.json [--request solicitacao.vyreq]` executa, em uma pasta temporária, o autoteste completo (configuração, chave cifrada, emissão, adulteração, renovação, reativação, revogação, gestão comercial com pagamento, duplicidade e autorização offline, DEMO, backup e restauração, auditoria). `--version` informa a versão. `--data-dir PASTA` usa uma pasta de dados explícita.
