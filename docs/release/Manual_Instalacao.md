# Manual de Instalação

**VYONIX DICOM Print {VERSION}** · Windows 10 e Windows 11, 64 bits

> Versão de desenvolvimento para homologação. Não validada para uso clínico.

## 1. Requisitos

| Item | Requisito |
|---|---|
| Sistema operacional | Windows 10 (versão 1809 ou posterior) ou Windows 11, 64 bits |
| Processador | x64 com 2 núcleos |
| Memória | 4 GB |
| Tela | 1024 × 768 ou maior |
| Permissão | Conta com direito de administrador para instalar |
| Espaço em disco | Aproximadamente 100 MB para o programa, mais o espaço dos dados |
| Python | Não é necessário — o instalador contém tudo o que o programa precisa |

## 2. Instalação

1. Execute `VYONIX_DICOM_Print_Setup_v{VERSION}_x64.exe`.
2. Confirme a solicitação de permissão do Windows (Controle de Conta de Usuário).
3. Leia o aviso sobre o conteúdo desta versão e clique em **Avançar**.
4. Mantenha a pasta padrão `C:\Program Files\VYONIX\DICOM Print` (recomendado).
5. Marque **Criar um atalho na área de trabalho**, se desejar. Mantenha marcadas as opções **Instalar o serviço Windows**, **Mostrar o ícone na bandeja** e **Firewall** para que os equipamentos DICOM consigam se conectar a qualquer momento.
6. Clique em **Instalar** e, ao final, mantenha marcada a opção para abrir o programa.

O instalador cria:

- a entrada **VYONIX DICOM Print** no menu Iniciar;
- o registro em **Configurações → Aplicativos → Aplicativos instalados**, com desinstalador;
- a pasta de dados `C:\ProgramData\VYONIX\DICOM Print`, com permissão de gravação para usuários do computador;
- o serviço Windows **VYONIX DICOM Print** (`VyonixDicomPrint`), com início automático atrasado e reinício automático em caso de falha;
- o início do ícone na bandeja ao entrar no Windows.

### Serviço Windows

O serviço executa a recepção DICOM (Storage SCP), a impressão DICOM (Print SCP) e a fila de impressão **mesmo com a janela do VYONIX fechada e depois de reiniciar o computador**. A janela passa a ser apenas o painel de controle: ao abri-la com o serviço ativo, o Dashboard mostra *Serviço Windows: em execução* e os botões da tela *Servidor DICOM* comandam o serviço. Sem o serviço (opção desmarcada ou serviço parado), a janela roda os servidores enquanto estiver aberta, como nas versões anteriores, e o Dashboard avisa.

- O serviço roda na conta **Sistema Local**, na sessão 0, sem interface. Ele enxerga as impressoras **instaladas no computador**; impressoras de rede conectadas só no perfil de um usuário podem não aparecer para o serviço. Instale-as para todos os usuários (*Configurações → Impressoras*, adicionando a impressora localmente ou via servidor de impressão com a conta do computador).
- Logs do serviço: `C:\ProgramData\VYONIX\DICOM Print\logs`. Início e parada também ficam no Visualizador de Eventos do Windows (*Logs do Windows → Aplicativo*).
- A interface e o serviço se comunicam por um *named pipe* local (`\\.\pipe\vyonix-dicomprint`), autenticado por uma chave aleatória criada pelo serviço. O canal não é acessível pela rede.
- Para controlar manualmente (Prompt de Comando como administrador): `sc stop VyonixDicomPrint`, `sc start VyonixDicomPrint`, ou *services.msc*.
- Verificação sem abrir a interface: `"C:\Program Files\VYONIX\DICOM Print\Vyonix.exe" --service-check --report "%TEMP%\vyonix-servico.json"` (código 0 = serviço respondendo e servidores atendendo C-ECHO).

**Limitação conhecida:** a pasta de dados continua gravável por todos os usuários do computador, porque a interface (usuário comum) e o serviço (Sistema Local) compartilham o banco. Restrinja o acesso físico e as contas do computador do VYONIX.

### Instalação silenciosa (implantação em vários computadores)

```
VYONIX_DICOM_Print_Setup_v{VERSION}_x64.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG="C:\Temp\vyonix-setup.log"
```

A instalação silenciosa instala por padrão o serviço, o ícone na bandeja e a regra de firewall. Para escolher as opções, use `/TASKS="service,tray,firewall,desktopicon"` (remova as que não quiser).

## 3. Onde ficam os dados

| Conteúdo | Pasta |
|---|---|
| Programa | `C:\Program Files\VYONIX\DICOM Print` |
| Banco de dados, backups, imagens recebidas, PDFs gerados, logs do serviço | `C:\ProgramData\VYONIX\DICOM Print` |
| Logs da interface e exportações de cada usuário | `%LOCALAPPDATA%\VYONIX\DICOM Print` |

Nenhum dado é gravado na pasta do programa. Antes de qualquer atualização do esquema do banco de dados, o VYONIX cria uma cópia de segurança em `C:\ProgramData\VYONIX\DICOM Print\backups`.

## 4. Atualização

Execute o instalador da nova versão sobre a instalação existente. O programa é substituído; banco de dados, configurações e logs são preservados. Feche o VYONIX antes de atualizar — o instalador solicita o fechamento se ele estiver aberto, para o serviço antes de substituir os arquivos e o inicia de novo ao final. Durante a atualização (alguns segundos), os equipamentos não conseguem enviar; eles costumam tentar de novo automaticamente.

## 5. Desinstalação

Use **Configurações → Aplicativos → Aplicativos instalados → VYONIX DICOM Print → Desinstalar**.

O desinstalador para e remove o serviço Windows e pergunta se os dados também devem ser removidos. A resposta padrão é **Não**: os dados permanecem e são reaproveitados em uma reinstalação. Na desinstalação silenciosa, os dados são sempre preservados.

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

O VYONIX recebe imagens na porta configurada (padrão 11112). As portas padrão são 11112 (recepção) e 11113 (impressão DICOM). A opção de firewall do instalador cria regras de entrada para o `Vyonix.exe` e para o `VyonixService.exe` em redes privadas e de domínio e as remove na desinstalação. Detalhes no *Guia de Configuração DICOM*.

## 8. Problemas comuns

| Sintoma | Ação |
|---|---|
| Mensagem "já está aberto nesta sessão" | O VYONIX já está em execução; abra pelo ícone na bandeja (ao lado do relógio). |
| Dashboard mostra "Serviço Windows: instalado, parado" | Inicie o serviço em *services.msc* ou com `sc start VyonixDicomPrint` (como administrador) e reabra o VYONIX. |
| Impressora aparece na lista, mas os trabalhos falham com "impressora não encontrada" | A impressora existe só no perfil do usuário; instale-a para o computador (ver *Serviço Windows*). |
| Erro informando banco de dados corrompido | Feche o programa e restaure o arquivo mais recente de `backups` para `database\vyonix.db`. |
| Aviso do SmartScreen ao executar o instalador | Esta compilação de homologação não possui assinatura digital de código. Clique em **Mais informações → Executar assim mesmo** somente se o arquivo foi obtido da fonte oficial e o SHA-256 confere. |
