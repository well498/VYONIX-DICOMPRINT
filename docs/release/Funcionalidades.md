# Funcionalidades Implementadas e Pendentes

**VYONIX DICOM Print {VERSION}** · prompt mestre atualizado (equipamentos, calibração, teste 3 × 3, BMP)

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
| — | Assinatura digital do instalador | **Pendente** | Requer certificado de assinatura de código |
| — | Validação para uso clínico / homologação regulatória | **Pendente** | Fora do escopo do software; não declarada |
| — | Chave de licença de produção | **Pendente** | Gerar com `license_admin keygen` antes da distribuição comercial |
