# VYONIX — Recuperar a instalação atual e instalar a versão de teste (passo a passo)

**Para quem:** o computador Windows do proprietário, onde o desinstalador do VYONIX roda mas não remove a instalação.
**Garantia:** nenhum passo apaga dados. O banco de dados, os estudos DICOM, os usuários, as configurações, a
auditoria e os backups ficam em `C:\ProgramData\VYONIX` e são **preservados**. O VYONIX DICOM Print não é tocado.
**Nada é feito sem você:** a primeira execução só lê; a recuperação só acontece depois de você ver o plano e digitar
`RECUPERAR`.
**Tempo:** cerca de 20 a 30 minutos (mais a reinicialização).

## Antes de começar (recomendado)

1. Feche o navegador com o VYONIX e qualquer janela preta do VYONIX.
2. **Cópia extra por conta própria** (opcional): copie a pasta `C:\ProgramData\VYONIX\Backups` para um pendrive. É só
   uma cópia; nada é apagado.

## Passo 1 — Diagnóstico (só lê; não altera nada)

1. Descompacte `VYONIX_Kit_P0_Recuperacao.zip` na Área de Trabalho.
2. Abra `VYONIX_P0\recuperacao` e dê dois cliques em **`Recuperar_VYONIX.cmd`**. Aceite o pedido de administrador.
3. A ferramenta **só lê** o computador. Ela não para serviços, não fecha programas, não renomeia pastas, não mexe no
   registro do Windows nem no banco de dados. O único arquivo gravado é o relatório
   `VYONIX_Recuperacao_<data>.html`, na Área de Trabalho, que abre no navegador.
4. No relatório confira:
   * **R0 — Cópias de segurança:** quantas existem e se estão íntegras (SHA-256 confere).
   * **R9 — Banco de dados:** onde está, o tamanho, o estado e se conecta.
   * **R3 — Serviços:** cada serviço do VYONIX e se ele **pertence** ao VYONIX Platform. Um serviço marcado
     **NÃO PERTENCE** nunca é alterado pela ferramenta.
   * **R4 — Processos:** quais programas da pasta do VYONIX estão abertos (somente estes seriam fechados).
   * **"O que a recuperação faria (nada foi feito)"**: o plano completo.
5. **Envie esse relatório.** Ele mostra a causa da falha no seu computador.
6. Na janela preta, responda **N** se quiser parar aqui. Nada foi alterado.

## Passo 2 — Aplicar a recuperação (com confirmação)

1. Na mesma janela, responda **S**. A ferramenta mostra **"O QUE A RECUPERAÇÃO VAI FAZER"**:
   * os serviços que serão parados e removidos (somente os do VYONIX Platform; nunca o DICOM Print nem serviços de
     outros programas);
   * os processos que serão fechados (somente os da pasta do programa);
   * a pasta que será **renomeada** (não apagada): `C:\Program Files\VYONIX\Platform` →
     `Platform.anterior-<data>`;
   * onde ficam os dados preservados, onde fica o backup e como ele será conferido;
   * os impactos e as limitações (o VYONIX fica fora do ar até reinstalar; o DICOM Print continua funcionando).
2. Leia. Para continuar, digite **RECUPERAR** e tecle Enter. **Qualquer outra resposta cancela, e nada é alterado.**
3. O que a ferramenta faz, nesta ordem:
   1. **Registra o estado anterior** em `C:\ProgramData\VYONIX\Backups\recuperacao-<data>\estado-anterior`: serviços,
      registro de Programas e Recursos (`.reg`), regras de firewall, lista de arquivos do programa.
   2. Para o Core, o Worker e o motor PACS. Com o banco ainda ligado, faz um **backup novo** (`vyonix.dump`; a leitura
      completa confere as somas de verificação das páginas). Depois **prova que ele restaura**: restaura o backup num
      banco temporário de verificação, compara a quantidade de linhas de todas as tabelas e apaga só esse banco
      temporário. Se o banco não estiver acessível, faz uma **cópia a frio** do banco (com tudo parado), conferida
      arquivo por arquivo. As configurações necessárias à restauração também são copiadas.
   3. **Se o backup não for confirmado, a ferramenta religa os serviços e para.** Nada é removido nem renomeado.
   4. Com o backup confirmado, ela remove os serviços do VYONIX Platform e fecha os processos da pasta do programa.
      Depois renomeia a pasta e, só se o desinstalador não existir mais, remove o registro órfão (a cópia `.reg` foi
      guardada no item 1).
4. Ao final abre um relatório com **"O que foi feito"**, o plano confirmado, "antes" e "depois". **Envie também
   este.**
5. Se o resultado for **PARCIAL** (por exemplo, um serviço aberto por outro programa ou um arquivo preso), nada foi
   apagado. Reinicie o Windows e execute `Recuperar_VYONIX.cmd` de novo: repetir é seguro.

## Passo 3 — Reiniciar o Windows

Reinicie mesmo que o relatório não peça. Assim o Windows libera serviços e arquivos.

## Passo 4 — Instalar a versão de teste por cima (atualização)

1. Execute **`VYONIX_Homologacao_Setup_x64.exe`** como administrador. Se aparecer o aviso de editor desconhecido:
   **Mais informações → Executar assim mesmo**.
2. O instalador reconhece os seus dados. Na última tela deixe marcado **"Concluir a atualização agora"** e clique em
   Concluir.
   Se a última tela oferecer **"Abrir o assistente do VYONIX DEPLOY"** (a instalação anterior nunca chegou a ser
   concluída), deixe marcado, conclua e aprove o plano no assistente. Os dados existentes são usados.
3. Uma janela mostra o andamento: backup do banco, migração e reinício dos serviços. Ao final ela confere o
   funcionamento. Se aparecer **"A atualização NÃO foi concluída"**, a operação parou com segurança: o erro está
   registrado e nada foi apagado. Siga "Se a atualização falhar", abaixo.

## Passo 5 — Validar (checklist)

Use o checklist `Checklist_Validacao_P0.pdf` (os 5 pontos, com as evidências a guardar).

## Se a atualização falhar — reversão

Os dados nunca são apagados. Há três níveis, do mais simples ao mais completo:

1. **Repetir:** execute o instalador de novo (ele retoma a partir do estado real).
2. **Reparar:** Menu Iniciar → VYONIX → **VYONIX - Reparar instalacao** (mostra o diagnóstico; digite SIM).
3. **Voltar à instalação anterior:** pasta `VYONIX_P0\recuperacao` → **`Reverter_VYONIX.cmd`**. Ela mostra o plano e
   pede que você digite **REVERTER**. Depois:
   * a pasta `Platform.anterior-<data>` volta a ser `C:\Program Files\VYONIX\Platform`. Se houver lá uma pasta
     incompleta, ela é renomeada para `Platform.descartada-<data>`, e não apagada. Se houver uma instalação nova
     completa, a reversão não a substitui e avisa;
   * o registro de Programas e Recursos volta, se estiver ausente;
   * os serviços são recriados pelo **reparo oficial** e o funcionamento é conferido.

   A reversão **não mexe no banco de dados**.
4. **Restaurar o banco a partir do backup** só é necessário se os dados ficarem diferentes do esperado. Isto
   **substitui** os dados atuais. Peça antes ao suporte; é uma operação com confirmação própria (`RESTAURAR <nome>`)
   e faz antes um backup do estado atual. O backup da recuperação fica em
   `C:\ProgramData\VYONIX\Backups\recuperacao-<data>` (`vyonix.dump` + `backup.json`). Os backups automáticos de cada
   atualização ficam em `antes-da-atualizacao-<execução>`.

## Coletar os registros (para enviar)

Envie a pasta inteira ou os arquivos abaixo (nenhum contém senhas):

| Arquivo | Onde |
|---|---|
| Relatórios da recuperação, da reversão e da validação | Área de Trabalho: `VYONIX_Recuperacao_*.html` / `.log`, `VYONIX_Reversao_*.html` / `.log`, `VYONIX_Validacao_*.html` |
| Instalação, atualização e desinstalação | `C:\ProgramData\VYONIX\Logs\instalador.log` e `atualizacao.log` |
| Relatórios técnicos do DEPLOY (PDF) | `C:\ProgramData\VYONIX\Deploy\relatorios` |
| Registro do instalador do Windows | `%TEMP%\Setup Log*.txt` (digite `%TEMP%` na barra do Explorador) |
| Diagnóstico do funcionamento | Menu Iniciar → VYONIX → **VYONIX - Verificar funcionamento** (abre o sistema ou, se algo falhar, um relatório com o que está parado) |

**Não envie** a pasta `Backups` nem os arquivos `secrets.json`: eles contêm dados de pacientes e segredos cifrados.
