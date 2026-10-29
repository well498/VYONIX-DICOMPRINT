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

Passo a passo para o proprietário: `Procedimento_Recuperacao_Instalacao_Proprietario.md`. Checklist:
`Checklist_Validacao_P0.md`. Garantias da ferramenta `Recuperar_VYONIX` (pedido de 29/10, 17:05):

| Exigência | Como a ferramenta atende |
|---|---|
| Primeira execução só diagnóstico | Sem `-Aplicar` nenhum comando que altere algo é executado (teste automático `test_recovery_diagnosis_path_is_strictly_read_only`; CI 2.13 compara serviços, registro, arquivos do programa, backups e firewall antes/depois). Única gravação: o relatório HTML na Área de Trabalho |
| Identificar o que pertence ao VYONIX | Serviço pertence se o programa dele está em `Program Files\VYONIX\Platform`; processos idem; banco pelo `-D` do serviço do PostgreSQL. Serviço com o mesmo nome e programa em outro lugar: **NÃO PERTENCE**, nunca alterado. DICOM Print listado como nunca alterado |
| Confirmação explícita com plano | Plano exibido antes (serviços, processos, pasta, dados, backup, impactos, limitações, reversão); só `RECUPERAR` continua; outra resposta → código 3, nada alterado |
| Integridade do banco + backup consistente + prova de restauração | Core/Worker/PACS parados (sem escritas); `pg_dump` completo (lê todas as páginas, com somas de verificação ativas); restauração num banco temporário `vyonix_verif_*` e comparação da contagem de linhas de todas as tabelas; `backup.json` compatível com a restauração do DEPLOY. Sem banco acessível: cópia a frio conferida por SHA-256 de cada arquivo + estado "shut down" (`pg_controldata`). Último recurso: backup existente íntegro e legível. **Sem backup confirmado: religa os serviços e para (código 4)** |
| Estado anterior registrado | `Backups\recuperacao-<data>\estado-anterior`: serviços (JSON + `.reg` + recuperação automática), registro de desinstalação, firewall, lista de arquivos; configurações em `configuracao\` |
| Reversão | `Reverter_VYONIX.cmd`: pasta de volta, registro de volta, serviços pelo reparo oficial, verificação; nunca toca o banco. Restauração do banco: operação separada com confirmação `RESTAURAR <nome>` |
| Falhas | Serviço preso → marcado para exclusão, aviso REINICIAR, resultado PARCIAL (código 5); arquivo preso → pasta não renomeada, nada apagado; reexecução segura |

Atualização após a recuperação: o instalador detecta os dados (ProgramData) e executa a **atualização** do DEPLOY
(backup → migrações → serviços → verificação). Em falha, a execução para, registra o erro, reverte os passos
reversíveis e **nunca apaga um banco existente ou de estado desconhecido** (corrigido em 29/10: antes, um banco
momentaneamente inacessível na captura podia ser tratado como "criado agora").

## 4. Testes

* Locais: `tests_deploy/test_uninstall.py` (12) e `tests_deploy/test_faults.py` (6): ordem desativar → parar →
  encerrar → excluir; serviço marcado para exclusão; execução interrompida abandonada; processos só da pasta do
  programa; diagnóstico sem comandos de alteração; plano antes da confirmação; backup e estado antes de remover;
  reversão sem tocar o banco; falhas simuladas só por variável de ambiente; reversão do banco nunca apaga banco
  existente/desconhecido.
* CI Windows `deploy-windows`:
  * **2.12** — desinstalar com o assistente aberto e uma execução interrompida; reinstalar; atualizar por cima;
    reparar; ferramenta de recuperação (diagnóstico, aplicar, reinstalar).
  * **2.13 (novo)** — diagnóstico só leitura (antes = depois); cancelamento antes da confirmação; falha na remoção de
    serviço (aberto por outro programa) + serviço alheio com o mesmo nome + falha ao renomear (arquivo preso) →
    parcial, nada apagado, processos alheios intactos, backup restaurado em banco temporário; reexecução (cópia a
    frio); reversão (sistema e dados de volta); falha **simulada** na migração (para, registra, backup antes,
    restauração e nova atualização); falha **simulada** na inicialização (registra; nova atualização conclui).
* **Pendente (critério de conclusão do P0):** execução no computador do proprietário (checklist); Windows 10 e 11
  (BLK-04); reinício real sem login (o CI do GitHub não pode reiniciar).
