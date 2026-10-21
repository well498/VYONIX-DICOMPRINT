# Notas da Versão

**VYONIX DICOM Print {VERSION}** · compilação {BUILD_DATE} · commit `{COMMIT}`

## Natureza desta versão

Versão de **desenvolvimento para homologação**, correspondente às **Fases 1 a 5** (Fundação, Comunicação DICOM, Imagens e calibração, Impressão e fila, DICOM Print SCP) do plano de 8 fases. Não é a versão comercial 1.0.0: o número `{VERSION}` indica uma pré-versão de 1.0.0.

**Não validada para uso clínico. Sem declaração de conformidade DICOM.**

## Requisito mínimo

Windows 10 64 bits (versão 1809 ou posterior) ou Windows 11. O executável usa Python 3.12 e Qt 6.

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
- Interface com os 12 itens de menu; Dashboard, Configurações, Histórico, Licença (ID da instalação) e Sobre; temas claro e escuro.
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
- **DICOM Print SCP (Fase 5):** Basic Grayscale e Basic Color Print Management Meta SOP Classes, Presentation LUT, Printer (N-GET com o estado real da impressora e da fila); Film Session, Film Box (STANDARD\C,R de 1 × 1 a 8 × 8) e Image Box (8 e 12/16 bits, MONOCHROME1/2, RGB, polaridade REVERSE); N-ACTION no Film Box e no Film Session. A impressão só é confirmada ao equipamento depois que as imagens estão gravadas e o trabalho está na fila. Layout, orientação, cópias e prioridade pedidos pelo equipamento são respeitados e aparecem como "Pedido DICOM Print" nos detalhes do trabalho.

## Não implementado nesta versão

| Recurso | Fase prevista |
|---|---|
| Declaração de conformidade DICOM | 8 |
| Motor de regras, editor e simulação | 6 |
| Serviço Windows, operação em segundo plano, bandeja do sistema | 7 |
| Licenciamento offline assinado, ferramenta de emissão | 8 |

## Limitações conhecidas

- O executável e o instalador não possuem assinatura digital de código; o Windows SmartScreen pode exibir aviso.
- Enquanto o serviço Windows não existir (Fase 7), o servidor DICOM só funciona com o VYONIX aberto, e todos os usuários do computador têm permissão de gravação na pasta de dados em `ProgramData`.
- JPEG Lossless e JPEG Extended (12 bits) ainda não são aceitos: o equipamento deve enviar sem compressão ou em outra sintaxe.
- "Enviado" significa aceito pelo spooler do Windows. O trabalho só passa a "Concluído" quando o driver informa que imprimiu; muitos drivers não informam, e o trabalho fica em "Enviado".
- O envio real ao spooler foi verificado no CI com a impressora "Microsoft Print to PDF". Impressão em papel, em impressoras físicas, não foi verificada e deve ser feita na homologação.
- DICOM Print: formatos ROW, COL, SLIDE, SUPERSLIDE e CUSTOM, Annotation Box, Print Job SOP Class e Image Overlay não são suportados (o equipamento recebe o status de erro correspondente, nada é impresso de forma diferente do pedido). Tamanhos de filme (ex.: 14INX17IN) usam o papel do perfil; densidades de filme não são aplicadas ao papel, salvo se a opção correspondente estiver ligada.
- DICOM Print verificado com equipamento simulado (pynetdicom); interoperabilidade com equipamentos reais deve ser verificada na homologação.
- Imagens multiframe com mais de 16 quadros: na impressão automática, sai só o primeiro quadro.
- Testes de recepção feitos com equipamento simulado (pynetdicom). Interoperabilidade com equipamentos reais deve ser verificada na homologação.
- Os testes automatizados foram executados em Windows Server 2022 no GitHub Actions. O teste em Windows 10 e 11 limpos, sem Python, deve ser feito na homologação (ver Relatório de Validação).
- A disponibilidade jurídica do nome VYONIX ainda deve ser verificada antes da distribuição comercial.
