# P0 — Desinstalação, atualização, reparo e recuperação no Windows

* **Data:** 29/10/2026 · **Situação:** correção implementada e testada no CI Windows (critério 2.12);
  **não considerada resolvida** até a validação no computador do proprietário.
* **Dados nunca são apagados** por nada descrito aqui: banco PostgreSQL, estudos DICOM, configurações, usuários,
  permissões, auditoria e backups ficam em `C:\ProgramData\VYONIX` e são preservados. O DICOM Print não é tocado.

## 1. Diagnóstico — por que o desinstalador "rodava mas não removia"

Sem acesso ao computador do proprietário, a causa foi reconstruída a partir do código e reproduzida no CI. Há
quatro mecanismos que, sozinhos ou juntos, produzem exatamente o sintoma relatado:

| # | Causa | Efeito |
|---|---|---|
| 1 | **O assistente do DEPLOY fica aberto em segundo plano** (é iniciado oculto ao fim da instalação e só fecha após 2 h sem uso). Ele executa arquivos de `Program Files\VYONIX\Platform` | O desinstalador não consegue apagar esses arquivos (em uso); a pasta fica com o programa "pela metade". Na reinstalação, a cópia por cima dos arquivos presos falha |
| 2 | **Execução interrompida do DEPLOY** (instalação que caiu no meio — p.ex. as falhas de 28/10) | Toda execução seguinte, **inclusive a desinstalação**, primeiro tentava retomar aquela instalação; se ela falhasse de novo, a desinstalação terminava sem remover nada — e o Inno não mostra esse erro |
| 3 | **Recuperação automática dos serviços** (reiniciar após falha) + vigia do banco (bc9cf28) | Se um serviço não para a tempo e o processo é encerrado, o próprio Windows o reinicia — e os arquivos voltam a ficar presos |
| 4 | **Serviço "marcado para exclusão"** (o Windows só o apaga de vez ao reiniciar quando algum programa o mantém aberto) | A reinstalação falhava ao recriar o serviço (erro 1072), sem mensagem clara |

## 2. Correções

* **Desinstalador (Inno):** antes de tudo, desliga a recuperação automática e o início automático dos 4 serviços
  (Core, Worker, PostgreSQL, motor PACS), para cada um e fecha os processos da pasta do programa (assistente esquecido,
  Orthanc/PostgreSQL órfãos); depois o DEPLOY remove serviços, regras de firewall e atalhos; ao final o que restar é
  removido e a pasta do programa é apagada. Se o Windows exigir reinício para soltar um serviço, isso é avisado.
* **DEPLOY:** execução interrompida de outro tipo (ou qualquer uma, na desinstalação) passa a ser registrada como
  **abandonada** em vez de retomada; remoção de serviço robusta (desativar → parar → encerrar pelo PID se preciso →
  excluir); passo final que encerra processos da pasta do programa; mensagem clara para o erro 1072 ("reinicie").
* **Atualização direta:** o instalador reconhece uma instalação anterior (dados em ProgramData) e, ao concluir, já
  vem marcado **"Concluir a atualização agora"** (backup do banco, migração e reinício dos serviços, com o progresso
  numa janela). Não é preciso desinstalar antes. Serviços e assistente são parados e fechados antes da cópia.
* **Reparar instalação:** novo atalho *Menu Iniciar → VYONIX → VYONIX - Reparar instalacao* (diagnóstico, plano de
  reparo e aplicação só depois de digitar SIM).
* **Registros:** `C:\ProgramData\VYONIX\Logs\instalador.log` (instalação, atualização e desinstalação, passo a passo)
  e `atualizacao.log`; os relatórios do DEPLOY continuam em `C:\ProgramData\VYONIX\Deploy\relatorios`.
* **Inicialização automática** (bc9cf28) preservada: serviços automáticos, contas de serviço, recuperação após falha
  reaplicada pela atualização (o CI confere).

## 3. Como recuperar a instalação atual (computador do proprietário)

Ferramenta `Recuperar_VYONIX.cmd` (pasta `recuperacao` do pacote de validação). Ela **não depende** da instalação
com defeito.

1. Copie a pasta para a Área de Trabalho e dê dois cliques em **Recuperar_VYONIX.cmd** (aceite o pedido de
   administrador). Ela faz primeiro **só o diagnóstico** e abre um relatório (`VYONIX_Recuperacao_<data>.html` na
   Área de Trabalho). **Envie esse relatório** — ele mostra qual das causas acima ocorreu no seu computador.
2. Ela pergunta se deve **aplicar** a recuperação. Responda **S** e digite **RECUPERAR**. O que ela faz:
   para e remove os 4 serviços do VYONIX Platform (nunca o DICOM Print), fecha processos da pasta do programa,
   **renomeia** (não apaga) a pasta do programa para `Platform.anterior-<data>` e remove o registro de desinstalação
   só se o desinstalador não existir mais (com cópia `.reg` na Área de Trabalho).
3. Se o relatório disser **REINICIAR**, reinicie o Windows.
4. Instale a nova versão normalmente. Ela reconhece os dados e, ao final, conclui a **atualização** (deixe marcado).
5. Rode **VYONIX - Validar instalacao** e siga o roteiro P0 (acesso pelo IP, reinício sem login).

## 4. Testes

* Locais: `tests_deploy/test_uninstall.py` (8): ordem desativar → parar → encerrar → excluir; serviço marcado para
  exclusão; execução interrompida abandonada na desinstalação; processos só da pasta do programa (nunca o próprio);
  instalador sem o DICOM Print e sem apagar dados; ferramenta de recuperação só leitura por padrão e sem tocar dados.
* CI Windows (`deploy-windows`, critério **2.12**): desinstalar **com o assistente aberto e uma execução
  interrompida** → nada preso, pasta do programa vazia, serviços removidos, dados preservados, registro gravado;
  reinstalar depois de desinstalar (dados reconhecidos, atualização); atualizar por cima com o assistente aberto;
  reparo de serviço apagado por fora; ferramenta de recuperação (diagnóstico sem alterar; aplicar libera a
  reinstalação; dados intactos; DICOM Print em execução).
* **Pendente (critério de conclusão do P0):** execução no computador do proprietário; Windows 10 e 11 (BLK-04).
