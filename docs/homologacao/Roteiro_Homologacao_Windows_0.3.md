# VYONIX 0.3.x — Roteiro de homologação no Windows (computador do proprietário)

> Preparado pelo A06 (Windows/DevOps) na MISSÃO 2 e revisado pelo coordenador. **Versão a homologar:** a
> primeira versão 0.3.x **com as correções de segurança da MISSÃO 2** (a 0.3.0 da execução 41816154805 tem as
> falhas R-01/R-02 e S-01/S-02 descritas em `docs/seguranca/Missao2_Auditoria_Seguranca.md` e **não deve ser
> usada** além de testes). O número da execução de CI e o SHA-256 do instalador são preenchidos pelo coordenador
> quando a CI da versão corrigida terminar — veja a tabela abaixo.

| Campo | Valor |
|---|---|
| Versão | 0.3.x (preencher) |
| Execução de CI (artefato `homologacao-windows`) | (preencher) |
| SHA-256 do `VYONIX_Homologacao_Setup_x64.exe` | (preencher) |

> **Leia antes de começar**
> - **Nada é feito sem a sua autorização.** Cada passo diz o que fazer; se tiver dúvida, pare e pergunte ao suporte.
> - **Use somente dados fictícios** (pacientes, médicos, exames). Não use dados reais de pacientes e **não conecte
>   equipamentos médicos reais**.
> - Este roteiro **não mexe no VYONIX DICOM Print**. Se o Print estiver instalado neste computador, não altere nada
>   dele.
> - Para cada passo marque **[ ] OK** ou **[ ] Falhou** e escreva uma anotação (o que apareceu, data e hora). Tire uma
>   captura de tela quando algo falhar (tecla Windows + Shift + S).
> - **Não use senhas de exemplo de documentos**: o repositório é público. Crie senhas suas.
> - Passar neste roteiro **não é certificação de segurança** nem de conformidade regulatória.

Data: ____/____/______   Responsável: ______________________   Computador: ______________________

---

## Passo 0 — Anotar como está hoje (versão 0.2.0)

**O que fazer:**
1. Abra o VYONIX atual (`https://localhost:8444`) com o seu usuário de gestor.
2. Anote quantos usuários, pacientes, exames (Imagens) e laudos existem. Tire uma captura de cada tela.
3. Opcional (recomendado): copie a pasta `C:\ProgramData\VYONIX\Backups` para um pendrive (só cópia; nada é apagado).
   Guarde o pendrive em lugar seguro: ele contém dados **não criptografados**.

**Resultado esperado:** números anotados para comparar depois.

Usuários: ____  Pacientes: ____  Exames: ____  Laudos: ____

[ ] OK  [ ] Falhou — anotação: ______________________________________________

---

## Passo 1 — Conferir que o instalador é o correto (SHA-256)

**O que fazer:**
1. Baixe o artefato **homologacao-windows** da execução indicada na tabela acima e descompacte o `.zip`.
   O instalador fica em `dist\installer-platform\VYONIX_Homologacao_Setup_x64.exe`.
2. Abra o **PowerShell** (Menu Iniciar → digite PowerShell → Enter) e digite, trocando o caminho:

   ```
   Get-FileHash -Algorithm SHA256 "C:\Users\SEU_USUARIO\Downloads\homologacao-windows\dist\installer-platform\VYONIX_Homologacao_Setup_x64.exe"
   ```

3. Para o Windows comparar sozinho (troque `<SHA>` pelo valor da tabela):

   ```
   (Get-FileHash -Algorithm SHA256 "C:\...\VYONIX_Homologacao_Setup_x64.exe").Hash -eq "<SHA>"
   ```

**Resultado esperado:** o código é exatamente o da tabela e o segundo comando responde **True**.
**Se der False: NÃO instale.** Avise o suporte.

[ ] OK  [ ] Falhou — anotação: ______________________________________________

---

## Passo 2 — Atualizar por cima da 0.2.0 (sem desinstalar)

**O que fazer:**
1. Feche o navegador com o VYONIX.
2. **Não desinstale a versão atual.** Dê dois cliques no instalador e aceite o pedido de administrador. Se o Windows
   avisar "editor desconhecido": **Mais informações → Executar assim mesmo** (o instalador ainda não tem assinatura
   digital).
3. Na última tela deixe marcado **"Concluir a atualização agora"** e clique em **Concluir**.
4. Uma janela preta mostra backup do banco, migração e reinício dos serviços. Aguarde "Atualização concluída".

**Resultado esperado:** "Atualização concluída" sem erros. Registro em `C:\ProgramData\VYONIX\Logs\atualizacao.log`.
**Se aparecer "A atualização NÃO foi concluída":** nada foi apagado. Não repita por conta própria; guarde o
`atualizacao.log` e avise o suporte (Passo 15).

[ ] OK  [ ] Falhou — anotação: ______________________________________________

---

## Passo 3 — Conferir que os dados foram preservados

**O que fazer:**
1. Abra `https://localhost:8444` e entre com o **mesmo** usuário e senha de gestor de antes.
2. Compare com o Passo 0: usuários, pacientes, exames e laudos.
3. Abra um laudo antigo já liberado e baixe o PDF.
4. Abra **Auditoria** e confira que os registros antigos continuam lá.
5. Em `C:\ProgramData\VYONIX\Backups` confira a pasta nova `antes-da-atualizacao-…` com `vyonix.dump` e `backup.json`.

**Resultado esperado:** mesmos números, mesmo login, laudo antigo abre, backup novo existe.

[ ] OK  [ ] Falhou — anotação: ______________________________________________

---

## Passo 4 — Inicialização automática depois de reiniciar o Windows

**O que fazer:**
1. Reinicie o Windows. **Não abra nada do VYONIX.**
2. Depois de entrar, espere **3 minutos** (o serviço principal inicia com atraso, de propósito).
3. No PowerShell: `Get-Service Vyonix* | Format-Table Name, Status, StartType`
4. Abra `https://localhost:8444`.

**Resultado esperado:** `VyonixPostgreSQL`, `VyonixCore`, `VyonixWorker` e `VyonixPacsEngine` **Running** e
**Automatic**; a tela de login abre sem você iniciar nada. (O VyonixDicomPrint, se existir, não faz parte do teste.)

[ ] OK  [ ] Falhou — anotação: ______________________________________________

---

## Passo 5 — Portas: o que fica aberto e o que fica só neste computador

**O que fazer (PowerShell):**

```
Get-NetTCPConnection -State Listen -LocalPort 8444,4242,4243,5544,8042 | Format-Table LocalAddress, LocalPort
Get-NetFirewallRule -Group VYONIX | Format-Table DisplayName, Profile, Enabled
```

**Resultado esperado:**
- **5544** (banco) aparece **somente em 127.0.0.1**.
- 8444 (sistema), 4242 (recepção DICOM) e 4243 (consulta DICOM) aparecem em 0.0.0.0.
- 8042 (motor do PACS) pode aparecer, mas **sem regra de firewall**.
- Regras de firewall do VYONIX só para 8444, 4242 e 4243.

[ ] OK  [ ] Falhou — anotação: ______________________________________________

---

## Passo 6 — Acesso pela rede local (outro computador e celular)

**O que fazer:**
1. Descubra o IP: PowerShell → `ipconfig` → "Endereço IPv4". IP: ____________________
2. Num **outro computador** da mesma rede, abra `https://IP:8444`. Teste também `http://IP:8444`.
3. No **celular** no **mesmo Wi-Fi**, abra `https://IP:8444`.
4. Teste de segurança: no outro computador, tente `http://IP:8042` e `http://IP:5544`.

**Resultado esperado:**
- Aviso de certificado (normal nesta versão: o certificado é gerado pela instalação; a troca pelo certificado da
  instituição está em `docs/seguranca/Missao2_Auditoria_Seguranca.md`, estratégia TLS). **Avançado → Continuar**.
  A tela de login aparece.
- `http://` é levado para `https://`.
- No celular, a tela de login aparece e é utilizável.
- `8042` e `5544` **não abrem**. **Se abrirem, anote como falha grave.**

[ ] OK  [ ] Falhou — anotação: ______________________________________________

---

## Passo 7 — Login institucional

**O que fazer:**
1. Entre com o gestor. Saia e tente entrar com a senha errada uma vez.
2. Em **Usuários e papéis**, crie (com senhas provisórias **suas**): `tecnico.homolog` (Técnico),
   `medico1.homolog` e `medico2.homolog` (Médico), `coord.homolog` (modelo **Coordenador do CDI**; ative em
   "Perfis da instituição" se necessário).
3. Em **Laudos → Médicos**, cadastre os dois médicos com CRM fictício (ex.: 000001/PB e 000002/PB) e vínculo com
   toda a organização.
4. Entre com cada novo usuário; o sistema deve pedir a troca da senha provisória.
5. Teste de segurança (novo): com o gestor, tente alterar os **próprios** papéis.

**Resultado esperado:** só usuário e senha na tela; senha errada mostra "Usuário ou senha inválidos"; faixa de
homologação visível; troca obrigatória da senha provisória; alterar os próprios papéis é **recusado**
("Você não pode alterar os seus próprios papéis").

[ ] OK  [ ] Falhou — anotação: ______________________________________________

---

## Passo 8 — PACS: enviar um exame de teste (simulado)

**O que fazer:**
1. Como gestor: **Pacientes → Novo paciente** → `Paciente Ficticia Teste`, prontuário `HML-030`.
2. Menu Iniciar → VYONIX → **"VYONIX Homologacao - Enviar exame simulado"**; informe `HML-030`, o nome e Enter no
   número de acesso.

**Resultado esperado:** `"sent": 8, "failed": 0` e "Estudo sintético enviado". Nenhum equipamento real é usado.

[ ] OK  [ ] Falhou — anotação: ______________________________________________

---

## Passo 9 — RIS: o técnico vê e prepara o exame

**O que fazer:** entre como `tecnico.homolog` → **Painel do técnico** → aguarde 1–2 min → **Filtrar** → clique no
exame da `Paciente Ficticia Teste`.

**Resultado esperado:** o exame aparece em "Aguardando preparação" com 8 imagens, origem SIMULADOR_HML.

[ ] OK  [ ] Falhou — anotação: ______________________________________________

---

## Passo 10 — Viewer

**O que fazer:** no painel do exame, **Abrir Viewer**; role as imagens, teste janela/nível e zoom.

**Resultado esperado:** nova aba com as 8 imagens sintéticas. As medidas **não têm validação clínica**.

[ ] OK  [ ] Falhou — anotação: ______________________________________________

---

## Passo 11 — Permissões: o técnico troca o médico; a coordenação não

**O que fazer:**
1. Como `tecnico.homolog`: **Trocar médico** → `medico1.homolog`, justificativa fictícia → confirmar. Troque para
   `medico2.homolog` e volte para `medico1.homolog`.
2. Entre como `coord.homolog` e abra o mesmo exame → **Trocar médico**.

**Resultado esperado:** o técnico troca ("Médico trocado", registrado na Auditoria); a coordenação **não** consegue
("Somente o Técnico em Radiologia…", sem botão).

[ ] OK  [ ] Falhou — anotação: ______________________________________________

---

## Passo 12 — Telelaudos: início do laudo, bloqueio e autoria

**O que fazer:**
1. Como `tecnico.homolog`: **Preparação do estudo** → itens obrigatórios → **Encaminhar para laudo**.
2. Como `medico2.homolog` (que **não** é o médico do exame): tente **Iniciar laudo** nesse exame.
3. Como `medico1.homolog`: **Laudos → Laudar → Iniciar laudo**, texto fictício, **Salvar rascunho**.
4. Como `tecnico.homolog`: tente **Trocar médico** ou mudar a prioridade do exame.
5. Como `medico2.homolog`: tente abrir e editar o laudo iniciado pelo médico 1.
6. Opcional: como `medico1.homolog`, **Prévia do rascunho**, **Liberar laudo** (pede a senha) e **Baixar PDF**.

**Resultado esperado:**
- Passo 2: recusado ("Este exame está atribuído a outro médico; só ele pode iniciar o laudo").
- Na lista: "Laudo iniciado em … · médico e prioridade bloqueados".
- Passo 4: troca de médico e de prioridade **recusadas** (mensagem de bloqueio).
- Passo 5: o médico 2 **não** lê nem edita o rascunho do médico 1 ("sob responsabilidade de outro médico").
- O PDF liberado informa que **não é assinatura digital ICP-Brasil**.

[ ] OK  [ ] Falhou — anotação: ______________________________________________

---

## Passo 13 — Backup (somente conferir; nada é restaurado)

**O que fazer:**
1. Abra `C:\ProgramData\VYONIX\Backups\antes-da-atualizacao-…\backup.json` no Bloco de Notas; anote "sha256".
2. PowerShell (administrador):

   ```
   Get-FileHash -Algorithm SHA256 "C:\ProgramData\VYONIX\Backups\antes-da-atualizacao-XXXX\vyonix.dump"
   icacls "C:\ProgramData\VYONIX\Backups"
   ```

**Resultado esperado:** o hash confere com o `backup.json`; `icacls` mostra só **SYSTEM** e **Administradores** (e,
na pasta PACS, o VyonixWorker) — nunca "Usuários" ou "Todos". Lembrete: o backup **não é criptografado**.

[ ] OK  [ ] Falhou — anotação: ______________________________________________

---

## Passo 14 — Kit de recuperação: somente diagnóstico (só leitura)

**O que fazer:** na pasta do kit já entregue (`VYONIX_P0\recuperacao`), dê dois cliques em **`Recuperar_VYONIX.cmd`**,
aceite o pedido de administrador; o relatório `VYONIX_Recuperacao_<data>.html` abre. Quando perguntar se aplica a
recuperação, responda **N**. **Não digite RECUPERAR.**

**Resultado esperado:** relatório com R0 (backups), R3 (serviços), R9 (banco) e "O que a recuperação faria (nada foi
feito)"; os serviços continuam rodando (`Get-Service Vyonix*`).

[ ] OK  [ ] Falhou — anotação: ______________________________________________

---

## Passo 15 — Reversão (conhecer o caminho; executar só com autorização)

**Só ler e conferir; não executar sem autorização expressa do proprietário e do suporte:**
1. Existem: o backup `antes-da-atualizacao-…`, o atalho **"VYONIX - Reparar instalacao"** e `Reverter_VYONIX.cmd`.
2. Ordem, da mais simples à mais completa: (1) **repetir** o instalador; (2) **reparar** pelo atalho (pede SIM);
   (3) **restaurar o banco** do backup (substitui os dados atuais; só com o suporte; exige `RESTAURAR <nome>` e faz
   backup do estado atual antes); (4) `Reverter_VYONIX.cmd` só desfaz uma recuperação do kit.
3. Voltar aos programas da 0.2.0 depois da migração do banco **não foi testado**: não tente sem o suporte.

**Resultado esperado:** você localizou os itens e sabe quem chamar. Nenhuma reversão executada.

[ ] OK  [ ] Falhou — anotação: ______________________________________________

---

## Passo 16 — Juntar os registros para enviar

Envie (sem senhas): este roteiro preenchido e as capturas; `C:\ProgramData\VYONIX\Logs\instalador.log` e
`atualizacao.log`; `C:\ProgramData\VYONIX\Deploy\relatorios` (PDF); `VYONIX_Recuperacao_*.html`.
**Não envie** a pasta `Backups`, `secrets.json` nem a pasta `tls`.

**Resultado geral:** [ ] Aprovado  [ ] Reprovado — passos com falha: _____________________

Assinatura do proprietário: ______________________   Data: ____/____/______
