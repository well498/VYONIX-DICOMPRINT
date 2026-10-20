# Manual de Instalação

**VYONIX DICOM Print {VERSION}** · Windows 7 SP1 a Windows 11, 64 bits

> Versão de desenvolvimento para homologação (Fase 1 — Fundação). Não validada para uso clínico.

## 1. Requisitos

| Item | Requisito |
|---|---|
| Sistema operacional | Windows 7 SP1, 8.1, 10 ou 11, sempre 64 bits |
| Atualização obrigatória no Windows 7 | KB2533623 (o instalador verifica e avisa se faltar) |
| Processador | x64 com 2 núcleos |
| Memória | 2 GB no Windows 7; 4 GB no Windows 10/11 |
| Tela | 1366 × 768 ou maior |
| Permissão | Conta com direito de administrador para instalar |
| Espaço em disco | Aproximadamente 100 MB para o programa, mais o espaço dos dados |
| Python | Não é necessário — o instalador contém tudo o que o programa precisa |

> **Windows 7:** a Microsoft encerrou as atualizações de segurança do Windows 7. O VYONIX funciona nele, mas, para uso com dados de pacientes, recomenda-se Windows 10 ou 11 atualizado, antivírus ativo e o computador sem acesso direto à internet.

## 2. Instalação

1. Execute `VYONIX_DICOM_Print_Setup_v{VERSION}_x64.exe`.
2. Confirme a solicitação de permissão do Windows (Controle de Conta de Usuário).
3. Leia o aviso sobre o conteúdo desta versão e clique em **Avançar**.
4. Mantenha a pasta padrão `C:\Program Files\VYONIX\DICOM Print` (recomendado).
5. Marque **Criar um atalho na área de trabalho**, se desejar.
6. Clique em **Instalar** e, ao final, mantenha marcada a opção para abrir o programa.

O instalador cria:

- a entrada **VYONIX DICOM Print** no menu Iniciar;
- o registro em **Configurações → Aplicativos → Aplicativos instalados**, com desinstalador;
- a pasta de dados `C:\ProgramData\VYONIX\DICOM Print`, com permissão de gravação para usuários do computador.

### Instalação silenciosa (implantação em vários computadores)

```
VYONIX_DICOM_Print_Setup_v{VERSION}_x64.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG="C:\Temp\vyonix-setup.log"
```

Acrescente `/TASKS="desktopicon"` para criar o atalho na área de trabalho.

## 3. Onde ficam os dados

| Conteúdo | Pasta |
|---|---|
| Programa | `C:\Program Files\VYONIX\DICOM Print` |
| Banco de dados, backups, imagens (fases futuras), logs do serviço | `C:\ProgramData\VYONIX\DICOM Print` |
| Logs da interface e exportações de cada usuário | `%LOCALAPPDATA%\VYONIX\DICOM Print` |

Nenhum dado é gravado na pasta do programa. Antes de qualquer atualização do esquema do banco de dados, o VYONIX cria uma cópia de segurança em `C:\ProgramData\VYONIX\DICOM Print\backups`.

## 4. Atualização

Execute o instalador da nova versão sobre a instalação existente. O programa é substituído; banco de dados, configurações e logs são preservados. Feche o VYONIX antes de atualizar — o instalador solicita o fechamento se ele estiver aberto.

## 5. Desinstalação

Use **Configurações → Aplicativos → Aplicativos instalados → VYONIX DICOM Print → Desinstalar**.

O desinstalador pergunta se os dados também devem ser removidos. A resposta padrão é **Não**: os dados permanecem e são reaproveitados em uma reinstalação. Na desinstalação silenciosa, os dados são sempre preservados.

## 6. Verificação após a instalação

Pelo Prompt de Comando, é possível verificar a instalação sem abrir a interface:

```
"C:\Program Files\VYONIX\DICOM Print\Vyonix.exe" --check --report "%TEMP%\vyonix-check.json"
```

O código de saída `0` indica sucesso, e o arquivo indicado contém versão, pastas e ID da instalação.

| Código de saída | Significado |
|---|---|
| 0 | Sucesso |
| 2 | Falha de inicialização (por exemplo, banco de dados corrompido) |
| 4 | A interface já está aberta nesta sessão |

## 7. Firewall

Esta versão não abre portas de rede. A orientação de firewall para recepção DICOM será incluída quando o servidor DICOM for entregue (Fase 2).

## 8. Problemas comuns

| Sintoma | Ação |
|---|---|
| Mensagem "já está aberto nesta sessão" | O VYONIX já está em execução; procure a janela na barra de tarefas. |
| Erro informando banco de dados corrompido | Feche o programa e restaure o arquivo mais recente de `backups` para `database\vyonix.db`. |
| Mensagem sobre a atualização KB2533623 (Windows 7) | Instale a atualização pelo Windows Update ou pelo Catálogo do Microsoft Update e execute o instalador de novo. |
| Aviso do SmartScreen ao executar o instalador | Esta compilação de homologação não possui assinatura digital de código. Clique em **Mais informações → Executar assim mesmo** somente se o arquivo foi obtido da fonte oficial e o SHA-256 confere. |
