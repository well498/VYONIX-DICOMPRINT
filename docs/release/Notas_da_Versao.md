# Notas da Versão

**VYONIX DICOM Print {VERSION}** · compilação {BUILD_DATE} · commit `{COMMIT}`

## Natureza desta versão

**Release candidata à homologação — não liberada para uso clínico.** Versão {VERSION}, revisão 6: correções da
auditoria de 23/10/2026 sobre a revisão 5 (interface, operação segura, trilha de auditoria) e a contenção do
incidente de chave INC-2026-10-23. A homologação física (equipamentos DICOM reais, impressoras físicas, Windows 10
e 11 limpos) segue o roteiro `docs/homologacao/` e ainda não foi executada. A lista detalhada do que foi
implementado e do que está pendente está em *Funcionalidades*.

São **quatro artefatos independentes**: o instalador comercial `VYONIX_DICOM_Print_Setup_v1.0.0_x64.exe` (também
publicado com o nome comercial `Vyonix_Setup.exe`, mesmo SHA-256) e, somente para o fornecedor,
`VYONIX_License_Manager.exe` (portátil), `VYONIX_License_Manager_Setup.exe` (instalação opcional) e
`VYONIX_License_Server.exe` (servidor central de licenças). O License Manager e o License Server não fazem parte do
instalador comercial.

A declaração de conformidade DICOM incluída é de homologação. Nenhuma conformidade regulatória é declarada.

## Requisito mínimo

Windows 10 64 bits (versão 1809 ou posterior) ou Windows 11. O executável usa Python 3.12 e Qt 6.

## Novidades da revisão 6 (auditoria de 23/10/2026)

- **Legibilidade e contraste (WCAG 2.2 AA):** tema escuro com paleta Qt completa; listas suspensas, menus, caixas de
  mensagem, barras de rolagem e dicas legíveis nos dois temas; verde e âmbar ajustados para 4,5:1 como texto.
- **Resolução, escala e monitores:** sem rolagem horizontal na janela padrão; linhas de botões e filtros em fluxo,
  rótulos com quebra, formulários que quebram a linha, grades responsivas (Painel, Calibração), diálogos roláveis e
  sempre dentro da tela. Verificado automaticamente em 11 configurações (1366 × 768 a 3840 × 2160, 100 % a 200 %,
  dois monitores) nos dois temas.
- **Pausar sistema / Retomar sistema / Abrir log** no cabeçalho. A pausa vale para a interface e para o serviço
  (fica no banco) e é registrada com o motivo na auditoria.
- **Alterações sensíveis com pausa segura:** salvar configurações de rede DICOM exige pausar; o reinício dos
  servidores espera as associações em andamento terminarem (até 60 s).
- **Trilha de auditoria com retenção própria** (`retention.audit_days`, padrão 5 anos), separada da limpeza dos
  eventos operacionais.
- **Validação honesta:** verificações que o ambiente de build não consegue comprovar (ex.: TPM real) aparecem como
  "não verificável neste ambiente", nunca como aprovadas.
- **Segurança de componentes:** SBOM CycloneDX e análise de vulnerabilidades conhecidas (pip-audit) a cada build,
  publicados com a release; conferência de que nenhuma dependência vulnerável entra no pacote distribuído.
- **Incidente de chave INC-2026-10-23:** o produto aceita a restrição de uma chave de emissão comprometida (só os
  documentos legítimos dela continuam válidos; documentos novos assinados com ela são recusados). A restrição entra
  em vigor na atualização que trouxer a lista exportada pelo fornecedor e a chave nova.
- **License Manager:** "Esqueci a senha…" (senha provisória em arquivo, liberada pela frase-senha de uma chave de
  emissão, com bloqueio após 5 tentativas) e "Exportar documentos legítimos…".

## Novidades da revisão 4 (licenciamento comercial por assinatura)

- **Estados comerciais:** ATIVA, PRÓXIMA DO VENCIMENTO, EM ATRASO, SUSPENSÃO PROGRAMADA, SUSPENSA, EXPIRADA e REATIVADA, com histórico completo das transições no License Manager, no License Server e no VYONIX. Estado financeiro separado do estado técnico de conectividade.
- **Avisos e carência configuráveis** (padrão: 5 dias antes, 7 dias de carência), prorrogação por perfis autorizados e ações que exigem confirmação de um administrador comercial; política assinada na licença.
- **Suspensão controlada:** só após inadimplência confirmada, avisos, fim da carência, contrato que a preveja e confirmação dos requisitos operacionais. Suspende apenas novas operações licenciadas; trabalhos aceitos são concluídos; imagens, filas, calibrações, configurações e histórico preservados; exportação dos exames sempre disponível (nova função *Exportar exames armazenados*). Licença permanente nunca é suspensa por mensalidade.
- **Autorizações de uso assinadas** (online com validade limitada e número de uso único; offline em arquivo `.vyauth`), sequência crescente (autorização antiga recusada), escopo de chave (a chave do servidor só assina autorizações).
- **Reativação** automática online, administrativa e offline, registrando data, origem e responsável.
- **VYONIX License Server:** API HTTPS (TLS 1.2+) para as instalações e para administração (usuários e perfis, auditoria encadeada, limites de taxa), tolerância a internet/servidor indisponíveis (nenhuma suspensão por falha de rede), revogação online, autoteste de ponta a ponta.
- **License Manager — Gestão Comercial:** cliente, CNPJ, instalação, plano, mensalidade, vencimento, último pagamento, dias de atraso, situação, histórico, notificações, suspensões e reativações; emitir, renovar, reemitir, conceder carência, programar suspensão, suspender, reativar, exportar autorização offline, publicar no servidor, auditoria. Novos perfis: Operador financeiro e Suporte técnico.
- **Banco Inter (opcional):** camada de cobrança com emissão de boleto/Pix, consulta autenticada, conciliação e avisos validados por consulta; boleto emitido, comprovante ou promessa não quitam; avisos repetidos ignorados. Credenciais somente no servidor.
- Perfis da clínica renomeados: *Administrador da clínica* e *Técnico da clínica*; detalhes comerciais visíveis somente ao administrador.

## Novidades da revisão 3 (arquitetura DICOM simplificada e VYONIX Reception)

- **Regras DICOM sem IP do equipamento:** "Equipamentos DICOM" passou a **Regras DICOM**. Cada regra é um destino: **AE Title de destino** (Called AE) + **porta** do VYONIX + serviço (C-STORE ou DICOM Print), com impressora, papel, orientação, layout, cópias, brilho/contraste/gama, cabeçalho/rodapé e **modo automático ou sob demanda**. Calling AE Title e IP/faixa de IP são **restrições opcionais**. Seleção pela porta + Called AE; ambiguidade impedida no cadastro e recusada na conexão; AE desconhecido recusado e registrado. Cadastros da versão anterior são convertidos sem perda.
- **Várias portas de escuta:** a porta padrão sugerida é 11112; regras podem ter porta própria, aberta e fechada automaticamente.
- **Configurar destino no equipamento:** tela com o IP correto do computador (várias placas de rede), AE Title e porta, copiar, C-ECHO, verificar porta, último equipamento conectado e erros de associação.
- **VYONIX Reception:** painel HTTPS na rede local, com login e perfis (Administrador, Técnico, Supervisor da recepção, Recepcionista): pesquisa por paciente, ID, atendimento, Accession Number, modalidade, regra, período e situações; IMPRIMIR EXAME, IMPRIMIR AGORA, composição das páginas; prevenção de duplicidade (aviso, motivo, supervisor, proteção contra cliques repetidos); controle de retirada independente; alertas; relatórios com folhas enviadas × confirmadas e economia estimada pela impressão sob demanda.
- Usuários Administrador e Técnico podem liberar as configurações técnicas no programa com `usuario:senha`.

## Novidades da revisão 2 (prompt mestre definitivo)

- **VYONIX Hardware ID:** combinação normalizada do UUID SMBIOS, placa-mãe, identificador do Windows, disco do sistema e da chave do TPM 2.0 (placas de rede físicas como componente auxiliar). Nenhum número de série sai do computador: só resumos criptográficos.
- **VYONIX Installation ID:** novo a cada instalação nova; preservado nas atualizações. O instalador distingue atualização de reinstalação pela entrada de desinstalação do Windows e pelo registro selado da instalação. A desinstalação encerra a ativação local; reinstalar exige nova licença.
- **Licença v2** assinada com Ed25519 (biblioteca `cryptography`), vinculada a Product ID, Hardware ID, Installation ID, License ID, recursos, quantidade de equipamentos e de impressoras e validade (DEMO, mensal, trimestral, semestral, anual, permanente e personalizada).
- **TPM 2.0:** chave não exportável criada pelo instalador no Microsoft Platform Crypto Provider; a licença que a inclui só é aceita se o TPM assinar um desafio novo (prova de posse). A solicitação de ativação também é assinada pelo TPM.
- **Integridade de estado:** registros de ativação, DEMO e horário selados (HMAC com chave protegida pelo DPAPI da máquina) em três locais (banco, `ProgramData\VYONIX\Licensing`, registro do Windows). Alteração detectada → funções suspensas e revalidação administrativa.
- **VYONIX Time Integrity:** linha do tempo confiável com relógio monotônico e identificação da inicialização do Windows; retrocesso além de 26 h suspende as funções até a correção ou a revalidação; adiantar e voltar o relógio não concede tempo; fuso horário, horário de verão e NTP não bloqueiam. Histórico temporal no banco.
- **DEMO de 5 dias (120 horas corridas):** por computador, não pausa ao fechar ou reiniciar, não renova ao reinstalar ou limpar configurações; tempo restante e aviso nas últimas 24 h; DEMO assinada pelo License Manager para nova avaliação autorizada.
- **Tela inicial** com *Iniciar demonstração de 5 dias*, *Ativar licença comercial*, *Exportar solicitação* e *Visualizar Hardware ID*; página Licença com diagnóstico exportável, revalidação, lista de revogação e vagas de impressoras.
- **Política comercial:** sem licença válida ou DEMO ativa, recepção C-STORE, impressão, Print SCP e regras ficam **suspensos** (associações recusadas como transitórias; trabalhos aguardam na fila). Cadastros e configurações continuam editáveis e são preservados na ativação.
- **VYONIX License Manager:** aplicativo administrativo independente (banco próprio): painel, clientes (com anonimização LGPD), produtos, importação de solicitações, emissão, renovação, **REATIVAR / EMITIR NOVA LICENÇA** com motivo e histórico do cliente, revogação e lista de revogação assinada, revalidação de horário/integridade, auditoria encadeada, backup cifrado (AES-256-GCM) e restauração, chaves de emissão cifradas com frase-senha e rotação, usuários com papéis (administrador, emissor, consulta).
- **Papel personalizado** (largura × altura em mm, em Configurações → Impressão), além de A4, A3, Carta e Ofício.

## Novidades da versão 1.0.0

- **Equipamentos independentes:** configurações de impressão exclusivas por equipamento, com versões, restauração, duplicação (cópia independente) e comparação; regras próprias de cada equipamento; hierarquia configurável (regra do equipamento → equipamento → pedido DICOM Print conforme a política → perfil da modalidade → global) com a origem de cada valor; impressão automática ou manual por equipamento.
- **Identificação da origem por AE Title + IP:** dois equipamentos podem ter o mesmo AE Title se tiverem IPs diferentes; ambiguidade é recusada com motivo claro.
- **Calibração visual avançada:** brilho, contraste e gama de −5,0 a +5,0 (setas ±0,5, passo fino 0,1/0,2, barra, campo, restaurar, indicador de não salvo, atalhos), com fórmulas documentadas aplicadas em ponto flutuante no mesmo pipeline da impressão; imagem recebida, arquivo (DICOM, JPG, PNG, BMP) ou padrão de teste; pré-visualização original × ajustada em segundo plano, zoom, antes/depois.
- **Teste de calibração 3 × 3** (três modos, quatro incrementos, ajuste nos limites, rótulos em faixa própria, pré-visualização da folha) e **calibração progressiva** com escolha da melhor imagem, novas rodadas, histórico e reversão.
- **Cabeçalho e rodapé BMP universais** de 3000 × 206 px (modelos brancos incluídos), personalização com conversão proporcional, aplicação em A4/A3, retrato/paisagem, na largura útil (considerando a área não imprimível do driver), ativação individual por equipamento.
- **Motor de layout:** layout personalizado, área não imprimível da impressora, alerta de resolução efetiva insuficiente, pré-visualização fiel da página (mesmo código da impressão) nos trabalhos e nas configurações do equipamento.
- **Banco e histórico:** migração 4 (configurações e versões por equipamento, regras por equipamento, rodadas de calibração) sem perda de cadastros; backup automático diário e manual verificados; restauração por `--restore-backup`.
- **Correção:** textos impressos (cabeçalho, rodapé, padrão de teste) agora saem com acentos — a fonte DejaVu Sans é distribuída com o programa.

## Implementado

- Instalador Windows x64 com atalhos, registro em Programas Instalados, desinstalador e preservação de dados em atualizações.
- Executável `Vyonix.exe` sem dependência de Python instalado, em distribuição enxuta (sem os componentes do Qt que o VYONIX não usa).
- Janela inicial ajustada à tela (abre maximizada em telas como 1366 × 768).
- Botões e diálogos padrão do Qt em português.
- Dados em `ProgramData` e `LocalAppData`; nada gravado na pasta do programa.
- Banco SQLite com modelo completo (equipamentos, impressoras, perfis, regras, instâncias, sessões de impressão, trabalhos, eventos, licenças, histórico), migrações atômicas com verificação de integridade e backup automático.
- Logs JSON rotativos, com mascaramento de dados de pacientes.
- Configurações validadas, auditadas, exportáveis e importáveis.
- Histórico de eventos com filtros e exportação CSV; histórico de alterações administrativas.
- Interface com os 13 itens de menu, todos implementados; temas claro e escuro.
- Máquina de estados dos trabalhos de impressão (base da fila da Fase 4).
- Modos de verificação automatizada: `--check` e `--smoke-test`.
- **Servidor DICOM (Storage SCP):** C-ECHO e C-STORE para 24 classes de imagem (CT, MR, CR, DX, US, MG, XA, RF, NM, PT, captura secundária), sintaxes não comprimidas, associações simultâneas com limite configurável (padrão 10).
- **Controle de associações:** AE Title local, AE Title e IP do equipamento, autorização; recusas com o código DICOM correto e registro no Histórico.
- **Armazenamento seguro:** gravação atômica, confirmação só após gravar, detecção de duplicatas e conflitos, um evento por associação.
- **Cadastro de equipamentos:** autorizar/bloquear, teste C-ECHO, histórico, desativação com preservação do histórico, importação e exportação.
- **Retenção (LGPD):** remoção automática de imagens e eventos antigos, com sobrescrita do arquivo antes de apagar.
- **Senha de administrador** para configurações, equipamentos e servidor.
- **Firewall:** regra opcional criada pelo instalador e removida na desinstalação.
- **Imagens (Fase 3):** decodificação de imagens não comprimidas e comprimidas (RLE, JPEG Baseline, JPEG 2000, JPEG-LS); LUT de modalidade, janela (VOI), MONOCHROME1, ajustes explícitos; pré-visualização com cache.
- **Calibração (Fase 3):** brilho, contraste, gama, níveis de preto e branco, inversão, escala e deslocamento físicos; padrão de teste com régua de 10 cm; perfis com histórico.
- **Impressão (Fase 4):** papéis A4, A3, Carta, Ofício, A5 e Tabloide e formatos de filme DICOM; layouts de 1 × 1 a 4 × 4; margens, espaçamento, bordas, cabeçalho, rodapé e numeração; resolução de saída configurável.
- **Impressoras (Fase 4):** detecção das impressoras do Windows (driver, porta, papéis, resoluções, cor), impressora padrão do VYONIX, página de teste; impressora virtual **VYONIX PDF** que grava PDFs em tamanho real.
- **Fila persistente (Fase 4):** impressão automática por série recebida, estados rastreados, chave de idempotência contra impressão duplicada, tentativas automáticas, recuperação após queda, reter, liberar, cancelar, tentar de novo, reprocessar e reimprimir; origem de cada configuração aplicada.
- **Perfis de impressão (Fase 4):** associação a impressora, modalidade ou equipamento.
- **Licenciamento offline (formato 2):** ver *Novidades da revisão 2* e o documento *Licenciamento e Ativação*. A ferramenta de linha de comando `license_admin` e o formato 1 (chave `hml-2026`) foram retirados: licenças antigas não são aceitas.
- **Declaração de Conformidade DICOM** (homologação) dos serviços implementados.
- **Serviço Windows (Fase 7):** `VyonixService.exe` (sem Qt) executa recepção, impressão DICOM e fila com a janela fechada e após reiniciar o computador; início automático atrasado e reinício em falhas; a interface se conecta ao serviço por *named pipe* local autenticado e comanda os servidores; configurações alteradas na interface são aplicadas pelo serviço sem reiniciá-lo; ícone na bandeja com o estado dos serviços; verificação `--service-check`.
- **Regras automáticas (Fase 6):** condições por AE Title, equipamento, modalidade, unidade, setor, origem, descrição do estudo, parte do corpo, número de imagens, filme pedido, horário (inclusive faixas que cruzam a meia-noite) e dia da semana, sem diferenciar maiúsculas nem acentos; ações para impressora, papel, orientação, layout, cópias, resolução, margens, textos, perfil, retenção, prioridade e "parar"; prioridade ajustável; simulação que mostra regra a regra por que se aplica ou não e o resultado final com a origem de cada valor; histórico, importação e exportação. Precedência: padrão < perfil < regra < pedido DICOM Print < escolha manual.
- **DICOM Print SCP (Fase 5):** Basic Grayscale e Basic Color Print Management Meta SOP Classes, Presentation LUT, Printer (N-GET com o estado real da impressora e da fila); Film Session, Film Box (STANDARD\C,R de 1 × 1 a 8 × 8) e Image Box (8 e 12/16 bits, MONOCHROME1/2, RGB, polaridade REVERSE); N-ACTION no Film Box e no Film Session. A impressão só é confirmada ao equipamento depois que as imagens estão gravadas e o trabalho está na fila. Layout, orientação, cópias e prioridade pedidos pelo equipamento são respeitados e aparecem como "Pedido DICOM Print" nos detalhes do trabalho.

## Não implementado nesta versão

Nenhum recurso do plano ficou sem implementação. Itens que dependem de recursos externos (certificado de assinatura de código, equipamentos e impressoras reais, TPM físico no ambiente de testes, validação clínica) estão em *Funcionalidades* e no *Relatório de Validação*.

## Limitações conhecidas

- O executável e o instalador não possuem assinatura digital de código; o Windows SmartScreen pode exibir aviso.
- Todos os usuários do computador têm permissão de gravação na pasta de dados em `ProgramData` (interface e serviço compartilham o banco).
- O serviço roda como Sistema Local: impressoras de rede conectadas apenas no perfil de um usuário podem não estar disponíveis para ele. A Microsoft não oferece suporte oficial à impressão GDI a partir de serviços; o envio foi verificado no CI com a impressora "Microsoft Print to PDF", mas deve ser homologado com as impressoras reais.
- JPEG Lossless e JPEG Extended (12 bits) ainda não são aceitos: o equipamento deve enviar sem compressão ou em outra sintaxe.
- "Enviado" significa aceito pelo spooler do Windows. O trabalho só passa a "Concluído" quando o driver informa que imprimiu; muitos drivers não informam, e o trabalho fica em "Enviado".
- O envio real ao spooler foi verificado no CI com a impressora "Microsoft Print to PDF". Impressão em papel, em impressoras físicas, não foi verificada e deve ser feita na homologação.
- DICOM Print: formatos ROW, COL, SLIDE, SUPERSLIDE e CUSTOM, Annotation Box, Print Job SOP Class e Image Overlay não são suportados (o equipamento recebe o status de erro correspondente, nada é impresso de forma diferente do pedido). Tamanhos de filme (ex.: 14INX17IN) usam o papel do perfil; densidades de filme não são aplicadas ao papel, salvo se a opção correspondente estiver ligada.
- DICOM Print verificado com equipamento simulado (pynetdicom); interoperabilidade com equipamentos reais deve ser verificada na homologação.
- Imagens multiframe com mais de 16 quadros: na impressão automática, sai só o primeiro quadro.
- Testes de recepção feitos com equipamento simulado (pynetdicom). Interoperabilidade com equipamentos reais deve ser verificada na homologação.
- Os testes automatizados foram executados em Windows Server 2022 no GitHub Actions. O teste em Windows 10 e 11 limpos, sem Python, deve ser feito na homologação (ver Relatório de Validação).
- **Licença:** sem licença válida ou DEMO ativa, as funções licenciadas ficam suspensas. Esta compilação aceita somente licenças assinadas pela chave `vyx-2026-01` (impressão digital 44DE:3181:0922:95DC:C478:0FDC); importe-a no License Manager. Para trocar de chave, siga a rotação descrita no *Manual do License Manager* (exige atualização oficial).
- **Limites da proteção offline:** nenhuma proteção exclusivamente offline é absoluta. Sem TPM, a clonagem integral do disco/máquina virtual reproduz os identificadores; restaurar uma imagem completa do disco devolve o estado anterior da DEMO e do histórico temporal; um administrador local que apague simultaneamente todos os locais do cofre pode reiniciar a demonstração local (a DEMO assinada pelo License Manager evita isso). Relógio adiantado em mais de 26 h com o computador reiniciado nesse estado é indistinguível do tempo real e exige revalidação ao voltar a data. A revogação só tem efeito no computador depois de instalada a lista de revogação.
- **TPM:** a camada TPM foi testada com TPM simulado (mesmo formato de chave do Windows) e, no Windows, depende de o computador ter TPM 2.0 habilitado; o runner do CI pode não ter TPM — ver o Relatório de Validação (LIC-02).
- **Reception:** o certificado HTTPS é gerado pelo próprio computador (aviso do navegador na primeira vez); a chave do certificado fica na pasta de dados. DICOM TLS não é oferecido. A confirmação "Impressão confirmada" depende de o driver informar a impressão.
- **Mesma porta para C-STORE e DICOM Print** não é suportada: cada serviço usa as suas portas.
- **Calibração:** as fórmulas de brilho, contraste e gama são parâmetros iniciais; a calibração é visual (não densitométrica) e não comprova qualidade diagnóstica.
- **Restauração do banco:** feita pela linha de comando com o serviço parado (a interface mostra o procedimento).
- Imagens coloridas são convertidas para tons de cinza na folha de teste 3 × 3.
- A disponibilidade jurídica do nome VYONIX ainda deve ser verificada antes da distribuição comercial.
