# VYONIX Medical Platform — Homologação interna no Windows

**Versão de homologação interna. Use somente dados fictícios. Não é validada para uso clínico.**

## 1. O que você vai instalar

| Item | Detalhe |
|---|---|
| Arquivo | `VYONIX_Homologacao_Setup_x64.exe` (artefato `homologacao-windows` do pipeline *deploy-windows*, execução manual com `flavor=homologacao`) |
| Inclui | Plataforma VYONIX (Core e Worker), banco PostgreSQL 17 próprio, motor DICOM Orthanc 1.13 (sem plugins), Viewer OHIF 3.13, assistente de instalação (DEPLOY) |
| Módulos | PACS, Viewer, RIS (Agenda, Central de Exames, Painel do técnico), Laudos — **liberados sem licença comercial** só nesta variante |
| Identificação | Faixa vermelha "HOMOLOGAÇÃO INTERNA — SEM LICENÇA COMERCIAL" em todas as telas; Licença e módulos mostra "Homologação interna" |
| Onde instalar | **Outro computador ou máquina virtual com Windows 10 (1809 ou mais novo) ou 11, 64 bits, sem o VYONIX DICOM Print**; 4 GB de memória e 10 GB livres no mínimo |
| Portas usadas | 8444 (sistema no navegador, HTTPS), 5544 (banco, só local), 4242 (recepção DICOM), 4243 (consulta DICOM), 8042 (motor, só local) |
| Internet | Não é necessária para usar. |

## 2. Instalação (uma vez)

1. Baixe o `VYONIX_Homologacao_Setup_x64.exe` (link no relatório de entrega) e execute-o como administrador.
   O Windows pode avisar que o editor é desconhecido (o instalador ainda não tem assinatura de código, BLK-07):
   clique em **Mais informações → Executar assim mesmo**.
2. Na última tela do instalador deixe marcado **"Abrir o assistente do VYONIX DEPLOY"** e clique em Concluir.
   O assistente abre no navegador (endereço `http://127.0.0.1:…/?t=…`). Se não abrir — ou depois, a qualquer
   momento —, use Menu Iniciar → **VYONIX → "VYONIX - Assistente de instalacao"** (aceite a pergunta do Windows).
   Se o navegador ainda assim não abrir, a janela preta mostra o endereço `http://127.0.0.1:…/?t=…`: copie-o
   inteiro e cole no navegador; deixe a janela preta aberta. Preencha:
   - Organização: `clinica-alfa` · Nome: `Clínica Alfa (fictícia)`
   - Administrador: `gestor.alfa` · Senha: uma senha sua com 10 caracteres ou mais (ex.: `Gestor-Alfa-2026!`)
   - Portas: deixe as sugeridas (8444 e 5544).
   Revise o plano e aprove. O assistente gera um relatório PDF da implantação. **Sem essa aprovação nada fica
   instalado e o endereço 8444 não abre.**
3. Menu Iniciar → **VYONIX → "VYONIX Homologacao - Preparar modulos"**. Aceite a pergunta do Windows
   (administrador). A janela mostra PACS, RIS e Laudos sendo ativados; termina com "Pronto".
4. Menu Iniciar → **VYONIX → "VYONIX - Abrir sistema"** (ou o navegador em `https://localhost:8444` ou
   `https://127.0.0.1:8444`). Na primeira vez, o navegador avisa que o certificado não é confiável (certificado
   autoassinado da instalação): **Avançado → Continuar**.
5. Se não abrir: `https://127.0.0.1:8444/api/v1/health` deve mostrar `"status": "ok"`; em Serviços do Windows os
   serviços **Vyonix…** devem estar "Em execução"; Menu Iniciar → **"VYONIX - Diagnostico"** mostra o estado.

## 3. Credenciais fictícias

| Perfil | Usuário | Senha | Observação |
|---|---|---|---|
| Gestor da clínica (administrador) | `gestor.alfa` | a que você definiu no assistente | criado na instalação |
| Técnico em Radiologia | `tecnico.alfa` | provisória `Provisoria-2026x` → no 1º acesso defina `Tecnico-Alfa-2026!` | criado no teste 2 |
| Médica laudadora | `dra.ficticia` | provisória `Provisoria-2026x` → no 1º acesso defina `Medica-Ficticia-2026!` | criada no teste 2 |
| Paciente fictícia | Maria Ficticia | prontuário `HML-001` | criada no teste 4 |

A tela de acesso pede só **usuário e senha**. Senhas provisórias são trocadas no primeiro acesso.

## 4. Roteiro de testes práticos

Para cada teste: **Objetivo · Como abrir · O que preencher · Ação · Resultado esperado · Como perceber falha ·
Evidência**. Evidência = captura de tela (tecla Windows + Shift + S) salva com o número do teste; anote no
formulário `docs/homologacao/formularios` ou num documento simples: data, hora, resultado (Aprovado/Reprovado) e
o que apareceu.

### Teste 1 — Entrar como gestor
- **Objetivo:** acesso só com usuário e senha; instituição identificada pelo sistema.
- **Como abrir:** `https://localhost:8444`.
- **Preencher:** `gestor.alfa` e a senha do assistente → **Entrar**.
- **Esperado:** "Olá, …", faixa vermelha de homologação, menu com Pacientes, Agenda, Painel do técnico, Central de
  exames, Laudos, Imagens, Usuários e papéis, Licença e módulos, Configurações e Auditoria.
- **Falha:** mensagem "Usuário ou senha inválidos" com a senha certa, tela em branco ou menu sem os módulos.
- **Licença e módulos:** PACS, RIS e Laudos aparecem como "Homologação interna (sem licença)".

### Teste 2 — Cadastrar técnico e médica
- **Como abrir:** menu **Usuários e papéis → Novo usuário**.
- **Preencher (técnico):** Nome `Tiago Técnico Fictício`, Usuário `tecnico.alfa` (ao sair do campo o sistema
  confere se o login está livre), Senha provisória `Provisoria-2026x`, Papel **Técnico** → **Criar usuário**.
- **Repita (médica):** Nome `Dra. Fictícia Teste`, Usuário `dra.ficticia`, mesma senha provisória, Papel **Médico**.
- **Esperado:** os dois aparecem na lista "Aguardando troca de senha".
- **Opcional:** em "Perfis da instituição → Modelos de perfil", ative "Coordenador do CDI" e dê ao técnico os dois
  papéis (um login, funções somadas).

### Teste 3 — Cadastro médico e vínculo
- **Como abrir:** menu **Laudos → botão Médicos**.
- **Preencher:** Usuário do médico `Dra. Fictícia Teste (dra.ficticia)`, CRM `000001`, UF `PB` → **Cadastrar médico**;
  na lista, **Incluir vínculo → Incluir vínculo** (toda a organização, a partir de hoje).
- **Esperado:** "Dra. Fictícia Teste — CRM 000001/PB" com "toda a organização: desde …".
- **Falha:** médica sem vínculo não consegue liberar laudos (é o comportamento correto se o vínculo faltar).

### Teste 4 — Paciente fictícia
- **Como abrir:** menu **Pacientes → Novo paciente**.
- **Preencher:** Nome `Maria Ficticia`; Identificador: Emissor `PRONTUARIO` (já vem preenchido), Número `HML-001`
  → **Cadastrar paciente**.
- **Esperado:** paciente com "PRONTUARIO HML-001".
- **Importante:** o simulador do teste 5 usa o mesmo prontuário; é por ele que o exame é associado à paciente.

### Teste 5 — Enviar exame DICOM simulado ao PACS
- **Como abrir:** Menu Iniciar → **VYONIX → "VYONIX Homologacao - Enviar exame simulado"**.
- **Preencher na janela:** prontuário `HML-001`, nome `Maria Ficticia`, número de acesso: Enter (vazio).
- **Ação:** o simulador envia 8 imagens sintéticas de TC por DICOM (C-STORE) para a porta 4242 deste computador,
  como um tomógrafo faria. Nenhum dado real.
- **Esperado:** `"sent": 8, "failed": 0` e "Estudo sintético enviado".
- **Falha:** "O PACS local não aceitou a conexão" → refaça o "Preparar módulos" (teste de instalação 3) e confira o
  serviço **VyonixPacsEngine** em execução (Serviços do Windows).

### Teste 6 — Exame aparece sozinho na Central de Exames (técnico)
- **Como abrir:** saia (Sair) e entre como `tecnico.alfa` / `Provisoria-2026x`; troque para `Tecnico-Alfa-2026!`.
  Menu **Painel do técnico**.
- **Esperado:** em até 1–2 minutos (sincronização do PACS e fim da recepção), o cartão **Aguardando preparação**
  mostra 1 e a lista mostra "Maria Ficticia — CT · TC de crânio (sintético) · 8 imagem(ns) · SIMULADOR_HML".
  Se ainda estiver "incompleto", aguarde 1 minuto e clique **Filtrar** (o sistema não presume que a transmissão
  terminou só porque a primeira imagem chegou).
- **Falha:** nada aparece depois de 3 minutos → registre a hora e abra "VYONIX - Diagnostico" no Menu Iniciar.

### Teste 7 — Viewer
- **Ação:** clique no exame (abre o **painel de ações**) → **Abrir Viewer**.
- **Esperado:** nova aba com o Viewer mostrando as imagens (círculos em degradê, 8 imagens; role com o mouse).
  Teste janela/nível, zoom e medição — **sem validação clínica de medidas**.

### Teste 8 — Painel de ações: comentário e anexo
- **Comentários:** escreva "Paciente orientada (comentário fictício)" → **Enviar comentário**. Esperado: autor,
  data e instituição; para outros usuários aparece como "novo".
- **Anexos:** **Anexos → Incluir arquivo** com um PDF ou imagem fictícia (até 10 MB). Esperado: o anexo na lista;
  **Abrir** mostra o conteúdo. Arquivos de outro tipo (ex.: .exe, .html) são recusados.
- **Opcional:** "Fotografar documento" e "Gravar áudio" funcionam melhor no celular/notebook com câmera e
  microfone (o áudio fica só como anexo, sem transcrição).

### Teste 9 — Checklist e encaminhamento
- **Ação:** **Preparação do estudo**: confira as "Verificações do sistema" (todas com ✓) e marque os três itens
  obrigatórios (Identificação, Procedimento, Qualidade) → **Encaminhar para laudo**.
- **Esperado:** "Estudo encaminhado à fila de laudos"; o cartão **Prontos para laudo** passa a 1.
- **Falha esperada (teste negativo):** antes de marcar os obrigatórios, o botão fica desabilitado; com uma
  "Suspeita técnica" aberta, o sistema recusa o encaminhamento.

### Teste 10 — Médica vê o exame na fila de laudos
- **Como abrir:** saia; entre como `dra.ficticia` / `Provisoria-2026x`, troque para `Medica-Ficticia-2026!`. Menu **Laudos**.
- **Esperado:** "Maria Ficticia" na lista com **Laudar** e **Abrir no Viewer**.

### Teste 11 — Laudo (implementado; não é assinatura digital)
- **Ação:** **Laudar → Iniciar laudo**, escreva um texto fictício → **Salvar rascunho** → **Prévia do rascunho**
  (PDF marcado "RASCUNHO — NÃO FINALIZADO") → senha da médica → **Liberar laudo** → **Baixar PDF do laudo**.
- **Esperado:** laudo liberado com versão e SHA-256; o PDF diz que **não é assinatura digital ICP-Brasil**.
- **Opcional:** "Minha assinatura" (imagem manuscrita fictícia, desenhada por você) — confirmar com a senha e
  autorizar o uso; o próximo laudo liberado mostra a imagem.

## 5. O que ainda NÃO testar (não implementado ou fora desta versão)

- Assinatura digital ICP-Brasil (PAdES) — BLK-14.
- Médicos da rede VYONIX entre instituições e compartilhamento entre instituições.
- Produção e remuneração médica; fechamento financeiro.
- Licenciamento integrado ao painel (emissão de licenças pela plataforma) — a homologação usa a variante sem
  licença; o License Manager continua sendo o emissor das licenças comerciais.
- Ativação online do DICOM Print pela plataforma (o Print segue com ativação offline e validação no License
  Server já existentes; para testes, o Print tem a demonstração de 120 h).
- Equipamentos e impressoras reais (BLK-02/03).

## 6. Desinstalar

Painel de Controle → Programas → **VYONIX Homologacao (plataforma)**. Serviços, regra de firewall e atalhos são
removidos; os dados ficam em `C:\ProgramData\VYONIX` (apague a pasta manualmente se quiser zerar).
