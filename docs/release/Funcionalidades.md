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

## Pendências externas ao software

| Item | Situação | Observação |
|---|---|---|
| Assinatura digital do instalador e dos executáveis | **Pendente** | Requer certificado de assinatura de código |
| Validação para uso clínico / homologação regulatória | **Pendente** | Fora do escopo do software; não declarada |
| Testes com TPM físico, troca real de disco/placa-mãe e equipamentos/impressoras reais | **Pendente** | Roteiro entregue (*Roteiro de Testes Manuais*, seção 6) |
| Chave de emissão | Atenção | A chave `vyx-2026-01` foi gerada no ambiente de desenvolvimento e entregue cifrada ao administrador. Recomenda-se gerar uma chave nova no License Manager do fornecedor e fazer a rotação em uma atualização. |
