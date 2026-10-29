# VYONIX — Recuperar a instalação atual e instalar a versão de teste (passo a passo)

**Para quem:** o computador Windows do proprietário, onde o desinstalador do VYONIX roda mas não remove a instalação.
**Garantia:** nenhum passo apaga dados. O banco de dados, os estudos DICOM, os usuários, as configurações, a
auditoria e os backups ficam em `C:\ProgramData\VYONIX` e são **preservados**. O VYONIX DICOM Print não é tocado.
**Tempo:** cerca de 20 minutos (mais a reinicialização).

## Antes de começar (5 minutos, recomendado)

1. Feche o navegador com o VYONIX e qualquer janela preta do VYONIX.
2. **Cópia de segurança extra** (opcional, mas recomendada): copie a pasta `C:\ProgramData\VYONIX\Backups` para um
   pendrive ou outra pasta. É só uma cópia; nada é apagado.

## Passo 1 — Diagnóstico (não altera nada)

1. Descompacte `VYONIX_Kit_P0_Recuperacao.zip` na Área de Trabalho.
2. Abra a pasta `VYONIX_P0\recuperacao` e dê dois cliques em **`Recuperar_VYONIX.cmd`**. Aceite o pedido de
   administrador.
3. A ferramenta faz **só o diagnóstico** e abre um relatório no navegador (`VYONIX_Recuperacao_<data>.html`, também
   salvo na Área de Trabalho).
4. **Envie esse relatório.** Ele mostra a causa da falha no seu computador.

## Passo 2 — Aplicar a recuperação

1. Na mesma janela, a ferramenta pergunta se deve aplicar. Responda **S**.
2. Digite **RECUPERAR** e tecle Enter.
3. O que ela faz:
   * para e remove os serviços do VYONIX Platform (Core, Worker, PostgreSQL, motor PACS) — **não** o DICOM Print;
   * fecha programas do VYONIX que ainda estejam abertos (por exemplo, o assistente esquecido em segundo plano);
   * **renomeia** a pasta `C:\Program Files\VYONIX\Platform` para `Platform.anterior-<data>` — **não apaga**;
   * remove o registro "VYONIX" de Programas e Recursos **somente** se o desinstalador dele não existir mais (salva
     antes uma cópia `.reg` na Área de Trabalho).
4. Ao final abre um novo relatório com "antes" e "depois". **Envie também este.**

## Passo 3 — Reiniciar o Windows

Reinicie mesmo que o relatório não peça: garante que o Windows liberou serviços e arquivos.

## Passo 4 — Instalar a versão de teste por cima (atualização)

1. Execute **`VYONIX_Homologacao_Setup_x64.exe`** como administrador (aviso de editor desconhecido:
   **Mais informações → Executar assim mesmo**).
2. O instalador reconhece os seus dados. Na última tela deixe marcado **"Concluir a atualização agora"** e clique em
   Concluir.
   Se em vez disso a última tela oferecer **"Abrir o assistente do VYONIX DEPLOY"** (a instalação anterior nunca
   chegou a ser concluída), deixe marcado, conclua e aprove o plano no assistente — os dados existentes são usados.
3. Uma janela mostra o andamento: **backup do banco**, migração e reinício dos serviços. Ao final ela verifica o
   funcionamento. Se aparecer "A atualização NÃO foi concluída", envie o arquivo
   `C:\ProgramData\VYONIX\Logs\atualizacao.log` — nada foi apagado.

## Passo 5 — Validar (os 5 pontos do P0)

Use o roteiro `Roteiro_Validacao_P0.pdf` e o atalho **Menu Iniciar → VYONIX → VYONIX - Validar instalacao**:

| # | O que validar | Como | Evidência |
|---|---|---|---|
| 1 | Atualização diretamente sobre a versão instalada | Passo 4 acima; seus pacientes e estudos continuam lá | Foto da lista de pacientes/estudos |
| 2 | Backend, frontend e banco funcionando | "VYONIX - Validar instalacao": C1–C4 APROVADO | Relatório `VYONIX_Validacao_*.html` |
| 3 | Inicialização automática após reiniciar | Reinicie, **não entre no Windows**, espere 5 min e abra o VYONIX de outro computador; depois rode a validação (C6/C7) | Foto com o horário + relatório |
| 4 | Acesso pelo IP | De outro computador/celular: `https://IP:8444` | Foto da tela de login |
| 5 | Desinstalar, reinstalar e reparar sem perda | (a) Menu Iniciar → VYONIX → **Reparar instalacao** (digite SIM); (b) Configurações → Aplicativos → VYONIX → Desinstalar; (c) instale de novo e deixe marcado "Concluir a atualização agora"; seus dados devem continuar lá | Relatórios + `C:\ProgramData\VYONIX\Logs\instalador.log` |

## Se algo der errado

* Nada é apagado: os dados continuam em `C:\ProgramData\VYONIX`.
* A pasta antiga renomeada (`Platform.anterior-<data>`) pode ser apagada **depois** que tudo estiver funcionando —
  ou mantida; ela não interfere.
* Envie: os relatórios da Área de Trabalho, `C:\ProgramData\VYONIX\Logs\instalador.log` e
  `C:\ProgramData\VYONIX\Logs\atualizacao.log`.
