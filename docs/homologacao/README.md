# Homologação física do VYONIX DICOM Print

Trilha separada do desenvolvimento (Comando Executivo §8). Estes testes **exigem ambiente real** e não podem ser
feitos no CI. Enquanto não forem executados e registrados, a homologação fica **pendente**. Nenhum deles valida
uso clínico ou diagnóstico.

> **Local dos ensaios (decisão do proprietário, 24/10/2026):** todos os casos são executados no **ambiente
> laboratorial offline** (rede isolada, sem internet, equipamentos e impressoras do laboratório, dados fictícios).
> Ensaio em campo — numa clínica, em equipamento em uso assistencial ou em rede de produção — **só com autorização
> expressa do proprietário**, registrada antes do ensaio (BLK-13). Para casos que pedem validação online (licença
> online, License Server), use um License Server do próprio laboratório, também na rede isolada.

* Versão a testar: a release candidata mais recente (rótulo “candidata à homologação — não liberada para uso clínico”).
* Registro: preencha um formulário por caso (`formularios/HF-NN.md`) e a planilha `registro_resultados.csv`.
* Evidências: fotos e capturas numa pasta por caso; nunca fotografe dados reais de pacientes (use fantoma ou paciente fictício).

## Casos e o que cada um exige

| Caso | Teste | Exige | Situação |
|---|---|---|---|
| [HF-01](formularios/HF-01.md) | Instalação limpa no Windows 10 | Responsável; PC ou VM com Windows 10 1809+ 64 bits recém-instalado, sem Python | Pendente |
| [HF-02](formularios/HF-02.md) | Instalação limpa no Windows 11 e atualização r5 → candidata | Responsável; PC ou VM com Windows 11 limpo | Pendente |
| [HF-03](formularios/HF-03.md) | Recepção de uma modalidade real | Equipamento DICOM real (TC, RM, RX, US ou mamógrafo) ou simulador de fabricante; técnico do equipamento | Pendente |
| [HF-04](formularios/HF-04.md) | Erros de comunicação | Mesmo ambiente do HF-03 | Pendente |
| [HF-05](formularios/HF-05.md) | Impressão física — layouts e papel | Impressora física (laser ou jato de tinta) e, se houver, impressora de filme | Pendente |
| [HF-06](formularios/HF-06.md) | Escala física e margens | Impressora do HF-05; régua milimetrada | Pendente |
| [HF-07](formularios/HF-07.md) | Calibração no papel (folha 3×3) | Impressora do HF-05; profissional que avalie a imagem | Pendente |
| [HF-08](formularios/HF-08.md) | Qualidade da imagem impressa | Profissional de radiologia (avaliação visual, não diagnóstica) | Pendente |
| [HF-09](formularios/HF-09.md) | Pausar e retomar com equipamento real | Ambiente do HF-03 e HF-05 | Pendente |
| [HF-10](formularios/HF-10.md) | Reinicialização do Windows | Ambiente do HF-01 | Pendente |
| [HF-11](formularios/HF-11.md) | Recuperação após falha | Ambiente do HF-05 | Pendente |
| [HF-12](formularios/HF-12.md) | Licenciamento em computador real | License Manager do fornecedor; computador do HF-01 (e com TPM 2.0, se houver) | Pendente |
| [HF-13](formularios/HF-13.md) | Interface em monitor real | Monitores reais em 1366×768 e 1920×1080 (100%, 125%, 150%) e, se houver, 4K | Pendente |
| [HF-14](formularios/HF-14.md) | Desinstalação e reinstalação | Ambiente do HF-01 | Pendente |

## Ordem sugerida

1. HF-01, HF-02, HF-13 e HF-14: só exigem Windows e monitores.
2. HF-05, HF-06 e HF-07: exigem impressora.
3. HF-03, HF-04, HF-08 a HF-11: exigem equipamento DICOM (ou simulador de fabricante) e impressora.
4. HF-12: exige o License Manager do fornecedor (com a chave nova, depois do INC-2026-10-23).

## Critério para considerar a homologação concluída

* Todos os casos executados, com resultado e evidência anexados.
* Nenhuma falha bloqueante aberta (falhas não bloqueantes registradas no backlog).
* Formulários assinados pelo executor e pelo responsável.
