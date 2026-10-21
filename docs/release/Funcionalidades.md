# Funcionalidades Implementadas e Pendentes

**VYONIX DICOM Print {VERSION}** · prompt mestre atualizado (equipamentos, calibração, teste 3 × 3, BMP) e prompt mestre definitivo (licenciamento, TPM, DEMO, Time Integrity, VYONIX License Manager)

Legenda: **Implementado** (código e testes automatizados) · **Parcial** (implementado com a limitação descrita) · **Pendente**. "Verificação manual" indica o que depende de equipamentos e impressoras reais (ver *Roteiro de Testes Manuais*).

| Seção | Requisito | Situação | Observação |
|---|---|---|---|
| 1.1 | Identificador interno, cadastro completo (inclui impressora e perfil) | Implementado | |
| 1.1 | Identificação da origem por AE Title + associação, com conflitos | Implementado | AE Title igual só com IPs diferentes; ambiguidade recusada |
| 1.1 | Dois equipamentos da mesma modalidade com parâmetros diferentes | Implementado | Teste automatizado com dois CTs |
| 1.2 | Regras por equipamento com os 16 parâmetros | Implementado | "Perfil de calibração associado" = perfil da impressora (níveis, escala, deslocamento) |
| 1.2 | Criar, editar, duplicar, excluir, ativar/desativar, importar, exportar, restaurar | Implementado | Restaurar = versões anteriores da regra |
| 1.3 | Hierarquia explícita e configurável, origem de cada valor | Implementado | Configurável pela política do pedido DICOM Print |
| 2.1 | Controles com setas, campo, barra, valor, restaurar, indicador | Implementado | |
| 2.2 | Escala −5,0 a +5,0, incremento 0,5, passos finos 0,1 e 0,2 | Implementado | |
| 2.3 | Fórmulas distintas, gama 2^(G/5), direção documentada, sem quantização prematura | Implementado | saída = entrada^(1/γ); cálculo em float32 antes dos 8 bits |
| 3.1 | Imagem recebida do equipamento com dados técnicos e miniatura | Implementado | Sem dados do paciente |
| 3.2 | Abrir DICOM (com/sem extensão), JPG, PNG, BMP com validação | Implementado | |
| 3.3 | Padrão de teste gerado | Implementado | Inclui elementos geométricos e níveis numerados |
| 4 | Original × Ajustada em tempo real, zoom, ajuste à janela, lado a lado, antes/depois, valores, restaurar, salvar, cancelar, indicador, segundo plano | Implementado | |
| 4 | Mesmo pipeline da impressão; Modality LUT, VOI/janela, Presentation LUT, fotometria | Implementado | Pré-visualização = mesma função de renderização e calibração |
| 5 | Folha 3 × 3, três modos, incrementos 0,1/0,2/0,5/1,0, limites, rótulos, informações da folha, pré-visualização | Implementado | Imagens coloridas convertidas para cinza na folha |
| 6 | Calibração progressiva, escolha, novas rodadas, histórico, reverter | Implementado | Avaliação visual: verificação manual |
| 7.1–7.2 | header.bmp e footer.bmp 3000 × 206, 24 bits, brancos, pasta print_templates | Implementado | |
| 7.3 | Identidade da Impressão: alterar, visualizar, restaurar; conversão proporcional | Implementado | Somente arquivos BMP são aceitos |
| 7.4 | Ajuste automático A4/A3, área imprimível, proporção, centralização, espaço reservado, limite de altura | Implementado | Área imprimível lida do driver no envio; verificação manual em impressoras reais |
| 7.5 | Ativação e espaçamentos por equipamento | Implementado | |
| 7.6 | Armazenamento persistente fora de Program Files, aviso se ausente/corrompido | Implementado | |
| 8 | A4, A3, retrato, paisagem, layouts padrão e personalizado | Implementado | Personalizado até 8 × 8 |
| 8 | Cálculo de áreas, margens imprimíveis, cabeçalho/rodapé, resolução efetiva e alerta | Implementado | |
| 9 | Banco: equipamentos, perfis, regras, calibração, histórico de calibração e de testes, versões | Implementado | Migração 4, sem apagar cadastros |
| 9 | Backup e restauração | Implementado | Restauração pela linha de comando com o serviço parado |
| 10 | Usabilidade: indicador, confirmação, duplicar, comparar, pesquisa, histórico, restaurar, mensagens, atalhos, pré-visualização da página | Implementado | |
| 11 | Testes automatizados dos critérios 1–24 | Implementado | Exceto os que exigem papel/equipamento real |
| 11 | Testes com equipamentos e impressoras reais | **Pendente** | Roteiro entregue; execução na clínica |
| 12 | Instalador `VYONIX_DICOM_Print_Setup_v1.0.0_x64.exe`, ZIP, código-fonte, documentação, relatório | Implementado | Gerado e validado no Windows Server 2022 (GitHub Actions) |

## Prompt mestre definitivo

| Seção | Requisito | Situação | Observação |
|---|---|---|---|
| 2 | C-STORE, C-ECHO, Print SCP (Film Session/Box, Image Box), fila, pré-visualização, histórico, reimpressão, eventos, impressoras do Windows | Implementado | Preservado da 1.0.0; C-STORE e Print SCP são servidores distintos |
| 3–7 | Equipamentos, regras (16 parâmetros), calibração −5..+5, imagem e pré-visualização, folha 3 × 3, BMP 3000 × 206 | Implementado | Preservado da 1.0.0 |
| 8 | A4, A3, Carta, Ofício e **formato personalizado**; retrato/paisagem; layouts 1 × 1 … 4 × 4 e personalizados | Implementado | Personalizado: largura × altura em Configurações → Impressão (50–1200 mm) |
| 8 | Spooler × confirmação física | Implementado | "Enviado" ≠ "Concluído" |
| 9 | License Manager independente: painel, clientes, produtos, emissão, renovação, reativação, revogação, histórico, backup, restauração, segurança, exportação assinada, banco próprio | Implementado | |
| 9 | `VYONIX_License_Manager.exe` portátil e `VYONIX_License_Manager_Setup.exe` | Implementado | Mesmo executável; gerados e validados no Windows (LM-01, LM-02) |
| 10 | VYONIX Hardware ID (UUID, placa-mãe, Windows, disco, MAC auxiliar, TPM), sem expor identificadores | Implementado | Resumos SHA-256 por componente |
| 11 | VYONIX Installation ID; licença vinculada a Product/Hardware/Installation/License ID, direitos, validade e assinatura | Implementado | |
| 11 | Desinstalação encerra a ativação; reinstalação gera novo ID e exige nova licença | Implementado | Validado no Windows (INS-08, LIC-07) |
| 11 | Atualização preserva ID, ativação, licença, cadastros, calibrações, configurações e BMP; distinção técnica | Implementado | Entrada de desinstalação do Windows + registro selado (LIC-06, INS-07) |
| 12 | Reativação administrativa com histórico do cliente, licença anterior e motivo | Implementado | REATIVAR / EMITIR NOVA LICENÇA |
| 13 | Camadas 1–5 (hardware, instalação, assinatura, TPM, integridade de estado) | Implementado | Limites documentados em *Licenciamento e Ativação* |
| 13 | TPM: chave não exportável e prova de posse | Implementado | Testado com TPM simulado; em hardware real depende de TPM 2.0 habilitado (LIC-02) |
| 14 | VYONIX Time Integrity: retrocesso, avanço, correções legítimas, monotônico, histórico protegido, bloqueio com diagnóstico e revalidação | Implementado | Testes com relógio simulado |
| 15 | DEMO 120 h corridas, por computador, tela inicial com 4 botões, aviso, suspensão, conversão preservando configurações, DEMO assinada | Implementado | Limite offline documentado |
| 16 | Tipos DEMO, mensal, trimestral, semestral, anual, permanente, personalizada; campos administrativos | Implementado | |
| 17 | Ed25519 pela biblioteca `cryptography`; chave privada só cifrada no License Manager; key ID; rotação; backup protegido; papéis; auditoria | Implementado | Sem criptografia própria (a verificação em Python puro da 1.0.0 foi substituída) |
| 18 | Ativação offline em 10 passos; DICOM Print sem funções de emissão | Implementado | |
| 19 | Bancos separados, backup, restauração, migrações (migração 5), corrupção, LGPD | Implementado | Anonimização de clientes no License Manager |
| 20 | 35 testes obrigatórios | Implementado | Matriz no *Relatório de Validação*; itens de hardware real no *Roteiro de Testes Manuais* |
| 21 | Três artefatos independentes; License Manager fora do instalador comercial; chave privada não distribuída | Implementado | Verificado no pipeline (LM-03 e varredura de chaves) |

## Prompt de desenvolvimento — arquitetura DICOM simplificada e VYONIX Reception

| Seção | Requisito | Situação | Observação |
|---|---|---|---|
| 2.1 | Servidor DICOM: IP/interface, porta, estado, AE Titles aceitos, firewall, teste, registro de associações | Implementado | Tela Servidor DICOM |
| 2.1 | Uma ou mais portas de escuta; porta sugerida 11112 | Implementado | Porta própria por regra |
| 2.2 | Adicionar Regra DICOM com os 13 campos; IP do equipamento não obrigatório | Implementado | |
| 2.3 | Seleção por porta + Called AE; Calling AE e IP como critérios opcionais; sem ambiguidade silenciosa; nunca pela modalidade | Implementado | `app/dicom/routing.py` |
| 2.4 | Restrições de origem opcionais (Calling AE, IP/faixa, combinação), rejeição registrada, aviso de que não são autenticação | Implementado | DICOM TLS não suportado (documentado) |
| 2.5 | Configurar destino no equipamento (IP correto com várias interfaces, copiar, C-ECHO, porta, último equipamento, erros) | Implementado | |
| 3 | C-STORE e DICOM Print separados; listeners separados sem conflito | Implementado | Porta compartilhada entre os dois serviços: não suportada |
| 4–5 | Regras independentes, duplicar/importar/exportar/habilitar; modo automático ou sob demanda por regra; conclusão não depende só do fim da associação | Implementado | |
| 6–8 | Calibração por regra, 3 × 3, BMP universais | Implementado | Preservado |
| 9–14 | VYONIX Reception: pesquisa, filtros, indicadores, situações de impressão, IMPRIMIR EXAME / AGORA, duplicidade, retirada, alertas, relatórios e economia estimada | Implementado | Navegador na rede local (HTTPS) |
| 15 | Perfis, autenticação, comunicação protegida (HTTPS), auditoria, LGPD, sem exposição à internet por padrão | Implementado | Certificado próprio do computador |
| 16–18 | License Manager, vinculação, DEMO | Implementado | Revisão 2 |
| 19 | Persistência fora de Program Files, backup, recuperação, retenção | Implementado | Migração 6 |
| 20 | 24 testes da nova arquitetura | Implementado | Matriz no *Relatório de Validação* |
| 21 | Distribuição (Vyonix.exe, serviço, Reception, instalador, License Manager portátil e instalador) | Implementado | O Reception é parte do serviço (sem executável separado) |

## Pendências externas ao software

| Item | Situação | Observação |
|---|---|---|
| Assinatura digital do instalador e dos executáveis | **Pendente** | Requer certificado de assinatura de código |
| Validação para uso clínico / homologação regulatória | **Pendente** | Fora do escopo do software; não declarada |
| Testes com TPM físico, troca real de disco/placa-mãe e equipamentos/impressoras reais | **Pendente** | Roteiro entregue (*Roteiro de Testes Manuais*, seções 6 e 7) |
| Certificado HTTPS de autoridade reconhecida para o Reception | Opcional | Substituir `cert.pem`/`key.pem` pelo certificado da instituição |
| Chave de emissão | Atenção | A chave `vyx-2026-01` foi gerada no ambiente de desenvolvimento e entregue cifrada ao administrador. Recomenda-se gerar uma chave nova no License Manager do fornecedor e fazer a rotação em uma atualização. |

## Licenciamento comercial por assinatura (prompt consolidado)

| Seção | Requisito | Situação | Observação |
|---|---|---|---|
| 1 | Componentes Server, Print Engine, Reception, License Client, License Manager, License Server | Implementado | License Client integrado ao VYONIX; License Server em executável próprio |
| 2–7 | Regras DICOM, C-STORE/Print SCP, calibração, BMP, automática/sob demanda, Reception | Implementado | Revisões anteriores, preservadas (testes c21–c28) |
| 8 | Modalidades demonstração, mensal, trimestral, semestral, anual, personalizada, permanente | Implementado | Permanente não suspensa por mensalidade/manutenção |
| 8 | Licença com ID, cliente, produto/edição, Hardware ID, Installation ID, recursos, limites, datas, política, assinatura | Implementado | Política comercial assinada na licença |
| 9 | Sete estados comerciais com histórico de transições | Implementado | LM, servidor e VYONIX (mesmo cálculo) |
| 9 | Estado financeiro separado da conectividade | Implementado | |
| 10 | Avisos, carência, quando suspender, perfis de prorrogação, ações com confirmação administrativa | Implementado | Padrões 5 e 7 dias |
| 10 | Mensagens ao administrador sem expor finanças aos demais usuários | Implementado | Recepção/técnicos: aviso neutro |
| 11 | Suspensão controlada com todas as salvaguardas; trabalhos aceitos concluídos; exportação | Implementado | |
| 12 | Reativação online, administrativa e offline, com data, origem e responsável | Implementado | |
| 13 | License Server: clientes/contratos/planos/vencimentos/financeiro/autorizações/suspensões/reativações/histórico/auditoria/cobrança | Implementado | Cadastro de clientes no License Manager; servidor guarda cliente e CNPJ por assinatura |
| 13 | API autenticada com TLS; proteção contra repetição, adulteração e autorizações vencidas | Implementado | Certificado fixado pela impressão digital na licença |
| 14 | Offline: validade definida, arquivos de renovação, importação, integridade, registros; limites documentados | Implementado | |
| 15 | Tolerância a servidor/internet indisponíveis, distinção das seis situações | Implementado | "Autorização local vencida" após a tolerância |
| 16 | License Manager portátil com Gestão Comercial e ações listadas | Implementado | Administra também o servidor (API) |
| 17 | Integração Banco Inter preparada (cobrança, consulta, aviso, conciliação, renovação automática) | Parcial | Testada contra reprodução local da API; homologação no sandbox do Inter pendente (credenciais) |
| 18 | Ed25519, chave privada só no ambiente administrativo, rotação, replay, versões | Implementado | Chave do servidor `vyx-srv-2026-01` com escopo restrito |
| 19 | Hardware ID/Installation ID, recuperação autorizada | Implementado | Revisão 2 |
| 20 | DEMO de 120 h | Implementado | Revisão 2 |
| 21 | Perfis comerciais e clínicos separados; auditoria; LGPD | Implementado | |
| 22 | 30 testes obrigatórios | Implementado | `tests/test_commercial.py` (c01–c30) e verificações LS-01/LS-02 no Windows |
| 23 | Distribuição: instalador comercial, License Manager (portátil e instalador), License Server, documentação | Implementado | License Server como executável de console; serviço do sistema configurado pelo administrador (Agendador de Tarefas/systemd) |
