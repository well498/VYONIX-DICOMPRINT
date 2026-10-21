# Roteiro de Testes Manuais (equipamentos DICOM e impressoras reais)

**VYONIX DICOM Print {VERSION}**

> Este roteiro é **separado** dos testes automatizados (ver *Relatório de Validação*). Ele cobre o que só pode ser verificado na instalação real — equipamentos DICOM, impressoras físicas e avaliação visual no papel. Preencha **Resultado** (Aprovado / Reprovado / Não aplicável), **Data**, **Responsável** e **Observações**. Nenhum item abaixo foi executado pelo fornecedor nesta compilação.

## Identificação do ambiente

| Item | Preenchimento |
|---|---|
| Unidade / clínica | |
| Computador (Windows, versão, memória) | |
| Impressora(s) e driver(s) | |
| Equipamentos DICOM (fabricante, modelo, AE Title, IP) | |
| Responsável pelos testes | |

## 1. Recepção e identificação dos equipamentos

| Nº | Procedimento | Esperado | Resultado | Data | Responsável | Observações |
|---|---|---|---|---|---|---|
| M-01 | Cadastrar o equipamento real e fazer "Verify/Echo" a partir dele | Último contato atualizado; evento no Histórico | | | | |
| M-02 | Enviar um estudo real (C-STORE) | Imagens gravadas; série vira trabalho de impressão | | | | |
| M-03 | Dois equipamentos com o mesmo AE Title e IPs diferentes enviam | Cada envio é atribuído ao equipamento certo | | | | |
| M-04 | Equipamento envia de um IP não cadastrado | Associação recusada, motivo no Histórico | | | | |
| M-05 | Impressão DICOM (Print SCP) a partir do equipamento | Filme vira trabalho; layout/cópias conforme a política | | | | |

## 2. Configurações independentes por equipamento

| Nº | Procedimento | Esperado | Resultado | Data | Responsável | Observações |
|---|---|---|---|---|---|---|
| M-10 | Configurar dois CTs com papel/layout/brilho/contraste/gama diferentes (ex.: A3 3×3 e A4 2×2) e enviar de cada um | Cada impressão sai com as configurações do seu equipamento | | | | |
| M-11 | Alterar um dos equipamentos e reenviar do outro | O outro não muda | | | | |
| M-12 | "Resultado final e origem" de cada equipamento | Origem de cada valor coerente com a hierarquia | | | | |
| M-13 | Impressão manual (impressão automática = Não) | Trabalho retido até ser liberado | | | | |

## 3. Calibração no papel

| Nº | Procedimento | Esperado | Resultado | Data | Responsável | Observações |
|---|---|---|---|---|---|---|
| M-20 | Imprimir o padrão de teste e medir a régua de 10 cm | 10 cm (± tolerância definida pela clínica) | | | | |
| M-21 | Folha 3 × 3 Gama × Contraste, incremento 0,5, em A4 e em A3 | Nove imagens distintas, rótulos legíveis, cabeçalho da folha completo | | | | |
| M-22 | Escolher a melhor imagem, nova rodada com 0,2 e depois 0,1 | Valores aplicados; histórico das rodadas registrado | | | | |
| M-23 | Salvar no perfil e imprimir um estudo real | Impressão com a calibração salva | | | | |
| M-24 | Reverter para a calibração anterior | Valores anteriores restaurados | | | | |
| M-25 | Comparar a pré-visualização com o papel | Diferenças apenas as esperadas da impressora (registrar) | | | | |

A avaliação visual não comprova qualidade diagnóstica. Calibração densitométrica/GSDF, se exigida, é um procedimento separado.

## 4. Cabeçalho e rodapé BMP

| Nº | Procedimento | Esperado | Resultado | Data | Responsável | Observações |
|---|---|---|---|---|---|---|
| M-30 | Instalar arte da clínica (BMP 3000 × 206) e imprimir em A4 retrato e paisagem | Arte na largura útil, proporcional, centralizada, sem cobrir imagens | | | | |
| M-31 | Repetir em A3 | Idem | | | | |
| M-32 | Instalar BMP de outro tamanho e aceitar a conversão | Sem deformação nem corte; fundo branco | | | | |
| M-33 | Desligar o cabeçalho em um equipamento e manter no outro | Apenas o equipamento com cabeçalho ligado o imprime | | | | |
| M-34 | Atualizar o VYONIX (instalar versão nova por cima) | Artes, calibrações e configurações preservadas | | | | |

## 5. Impressoras e serviço

| Nº | Procedimento | Esperado | Resultado | Data | Responsável | Observações |
|---|---|---|---|---|---|---|
| M-40 | Imprimir com a janela do VYONIX fechada (serviço) em cada impressora física | Impressão sai; trabalho "Enviado" ou "Concluído" | | | | |
| M-41 | Impressora sem papel/desligada durante a impressão | Aviso no trabalho; nova tentativa conforme configuração | | | | |
| M-42 | Reiniciar o computador com trabalhos na fila | Fila retomada sem impressão duplicada | | | | |
| M-43 | Backup manual e restauração com `--restore-backup` | Configurações voltam ao estado do backup | | | | |

## 6. Licenciamento em computadores reais

| Nº | Procedimento | Esperado | Resultado | Data | Responsável | Observações |
|---|---|---|---|---|---|---|
| M-50 | Instalar em computador com TPM 2.0 habilitado; Licença → Visualizar Hardware ID | "Chave do TPM 2.0: considerado"; prova de posse disponível | | | | |
| M-51 | Exportar solicitação, emitir no License Manager e ativar | License Manager mostra "assinada pelo TPM (prova verificada)"; licença válida | | | | |
| M-52 | Copiar a pasta do programa e os dados para outro computador | Licença recusada (outro computador / TPM) | | | | |
| M-53 | Substituir o disco do sistema (ou clonar para outro disco) | "disco do sistema substituído"; reativação pelo administrador funciona | | | | |
| M-54 | Trocar a placa-mãe (assistência técnica) | "placa-mãe diferente"; reativação pelo administrador funciona | | | | |
| M-55 | Desinstalar e reinstalar | Novo Installation ID; nova ativação exigida | | | | |
| M-56 | Atualizar para uma versão nova (instalar por cima) | Licença, configurações e artes BMP preservadas | | | | |
| M-57 | Com DEMO ativa: voltar a data do Windows 3 dias, abrir o VYONIX | Funções suspensas com o motivo; corrigir a data libera | | | | |
| M-58 | Com DEMO ativa: adiantar a data 10 dias e voltar | Nenhum tempo extra; nada bloqueado após voltar | | | | |
| M-59 | Mudar o fuso horário e o horário de verão | Nada bloqueado; contagem inalterada | | | | |
| M-60 | Diagnóstico → revalidação no License Manager → importar | Funções liberadas; revalidação recusada se importada de novo | | | | |
| M-61 | License Manager portátil em pen drive, em computador sem Python e sem o VYONIX | Abre, emite e exporta; dados ao lado do executável | | | | |
| M-62 | Backup protegido do License Manager e restauração em outro computador | Dados restaurados; chave exige a frase-senha | | | | |

## Conclusão

| Item | Preenchimento |
|---|---|
| Itens aprovados / total | |
| Pendências | |
| Parecer do responsável | |
