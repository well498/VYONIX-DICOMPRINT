# VYONIX — Roteiro de validação da instalação (P0)

**Objetivo:** confirmar, no computador de destino, que o VYONIX instala, abre pelo navegador neste computador e
pelo IP da rede, **funciona sem ninguém conectado ao Windows** e **volta sozinho depois de reiniciar**.

**Versão a validar:** instalador do commit `bc9cf28` (ou posterior), artefato `homologacao-windows` da execução
https://github.com/well498/VYONIX-DICOMPRINT/actions/runs/40896631587 — SHA-256
`2A9802E67522E9CC0CFCD7F570313FEEEDA0E61FA0A09D9BBFE3E5465B55FB29`.

**Você vai precisar de:** o computador de destino (sem o DICOM Print) e **outro computador ou celular na mesma
rede**. Nada aqui exige programação. O validador é **somente leitura**: não altera serviços, configurações nem dados.

**Arquivos do validador:** `Validar_VYONIX.cmd` e `Validar_VYONIX.ps1` (mesma pasta). Nos instaladores a partir
desta versão eles também ficam em Menu Iniciar → VYONIX → "VYONIX - Validar instalacao".

---

### Passo 1 — Instalar
1. Execute o instalador como administrador (aviso de editor desconhecido: **Mais informações → Executar assim mesmo**).
2. Na última tela, deixe marcado **"Abrir o assistente"** e conclua. No assistente, aprove o plano até o fim.
3. **Esperado:** ao final do assistente aparece "Acesso ao VYONIX" com "Sistema funcionando" e os endereços.
   **Falhou?** Tire uma foto da tela e envie.

### Passo 2 — Validar neste computador
1. Dê dois cliques em **`Validar_VYONIX.cmd`**. Uma janela preta mostra o andamento e o relatório abre no navegador
   (também fica salvo na Área de Trabalho como `VYONIX_Validacao_<data>.html`).
2. **Esperado agora:** C1, C2, C3 e C4 **APROVADO**; C5 aprovado ou atenção; C6 e C7 **PENDENTE** (ainda não reiniciou).
3. Anote o endereço mostrado em C4 (ex.: `https://192.168.0.20:8444/`).

### Passo 3 — Acessar de outro computador
1. No outro computador (ou celular), na mesma rede, abra o endereço anotado no passo 2.
   Também vale digitar `http://IP:8444` — ele muda sozinho para `https://`.
2. Aviso de certificado: **Avançado → Continuar**. **Esperado:** tela de login do VYONIX. Tire uma foto.

### Passo 4 — Reiniciar e testar **sem entrar no Windows**
1. No computador de destino: Iniciar → Ligar/Desligar → **Reiniciar**.
2. Quando aparecer a tela de login do Windows, **não entre**. Espere **5 minutos**.
3. No outro computador, abra de novo o endereço do passo 3. **Esperado:** tela de login do VYONIX. Tire uma foto
   com o horário visível. (Isto prova que o VYONIX funciona sem ninguém conectado.)

### Passo 5 — Validar depois do reinício
1. Agora entre no Windows e rode **`Validar_VYONIX.cmd`** de novo.
2. **Esperado:** C1–C6 **APROVADO** e C7 **APROVADO** ("o sistema web iniciou antes do login").
   Se C7 der **INCONCLUSIVO** (você entrou no Windows antes de o VYONIX iniciar), vale a foto do passo 4.

### O que me enviar
Os dois relatórios `VYONIX_Validacao_*.html` (passos 2 e 5) e as fotos dos passos 3 e 4.

### Critério de aprovação do P0
Passos 1–5 aprovados no computador de destino (C1–C7 aprovados, ou C7 inconclusivo com a foto do passo 4
aprovada). Repetir em Windows 10 e Windows 11 quando houver máquinas (BLK-04).

### Se algo falhar
O relatório diz o que falhou e "O que fazer". Não é preciso corrigir nada sozinho: envie o relatório.
