# VYONIX — Bloqueios

Registro dos impedimentos (Comando Executivo de continuidade, §4). Um bloqueio para só a tarefa afetada; as
"ações que podem continuar" seguem sem esperar.

**Tipos:**
* **Crítico:** impede uma operação por risco de segurança, integridade ou conformidade.
* **Externo:** depende de hardware, ambiente, fornecedor ou acesso.
* **Aprovação:** depende de decisão expressa do responsável.
* **Técnico:** a equipe resolve sozinha.

* **Atualizado em:** 2026-10-24
* **Bloqueios abertos:** 11. **Resolvidos:** 3.

## Abertos

| ID | Descrição | Módulo | Tipo · gravidade | Causa | Depende de | Quem resolve | Aprovação? | O que continua | Condição de desbloqueio |
|---|---|---|---|---|---|---|---|---|---|
| BLK-01 | Chave de emissão `vyx-2026-01` comprometida: documentos forjados com ela ainda são aceitos | License Manager, Print, Core, License Server | Crítico · alto | Chave gerada no ambiente de desenvolvimento; frase-senha enviada pelo chat (INC-2026-10-23) | Chave nova gerada pelo fornecedor e lista de documentos legítimos exportada | Fornecedor (passos 2–3) e desenvolvimento (passo 4) | Sim, para publicar a atualização e avisar os clientes | Mecanismo de restrição pronto e testado; todo o resto do projeto | `RESTRICTED_KEYS` preenchido com a lista exportada e a chave nova em `PUBLIC_KEYS`, numa release distribuída |
| BLK-02 | Nenhum teste com equipamento DICOM real | Print | Externo · alto | O CI só tem SCU simulado | Equipamento ou simulador de fabricante, operador | Responsável e técnico de campo | Não | Testes simulados e o resto do desenvolvimento | Roteiro HF-03 executado e registrado (`docs/homologacao/`) |
| BLK-03 | Nenhuma impressão em impressora física | Print | Externo · alto | O CI só tem "Microsoft Print to PDF" | Impressora (papel e, se houver, filme) | Responsável | Não | Impressão para PDF, testes de layout | Roteiros HF-05 a HF-07 executados |
| BLK-04 | Nenhum teste em Windows 10 ou 11 limpo | Print, DEPLOY | Externo · alto | O CI usa Windows Server 2022 | Máquinas ou VMs com Windows 10 1809+ e 11 | Responsável | Não | Testes no Server 2022 | Roteiros HF-01 e HF-02 executados |
| BLK-05 | Publicação de releases | Print, License Manager | Aprovação · médio | A publicação distribui software a terceiros | Sua decisão, por release | Responsável | **Sim** | Builds de teste no CI (artefatos) | Aprovação registrada no estado do projeto |
| BLK-06 | Finalidade pretendida e enquadramento regulatório indefinidos | Todos | Externo · alto | Exige especialista e decisão de negócio | Responsável técnico regulatório | Responsável | **Sim** (custo e escopo) | Avaliação documental preliminar (`docs/regulatorio/`) | Parecer de especialista sobre a classe e o caminho de cada módulo |
| BLK-07 | Revisão jurídica da distribuição do Orthanc (GPLv3) com o produto comercial | PACS | Aprovação · médio | Obrigação de licença | Advogado | Responsável | **Sim** (custo externo) | Desenvolvimento e testes internos do PACS (ADR-0012) | Parecer favorável ou decisão de outro motor |
| BLK-08 | Assinatura de código dos instaladores | Todos | Aprovação · médio | Requer certificado pago | Compra do certificado | Responsável | **Sim** (custo) | Builds sem assinatura | Certificado disponível como segredo do CI |
| BLK-09 | Credenciais do sandbox do Banco Inter | Comercial | Externo · médio | Sem acesso ao sandbox | Credenciais do Inter | Responsável | Não | Testes com a reprodução local da API | Teste no sandbox registrado |
| BLK-10 | Build do Viewer OHIF não pode ser feito neste ambiente de desenvolvimento | Viewer | Técnico · médio | O registro npm não é alcançável daqui (DNS) | Job de CI que baixa e compila o OHIF 3.13 | Desenvolvimento | Não | API DICOMweb, testes do PACS, todo o resto | Pacote do OHIF gerado e testado no CI |
| BLK-11 | Recepção por C-STORE no modo cloud não sabe a organização de destino | PACS | Técnico · médio | O Orthanc não é multiorganização | Mapeamento AE Title → organização no CORE | Desenvolvimento | Não | Modo edge (uma organização por servidor) | Roteamento implementado e testado; até lá a API recusa a sincronização no modo cloud |

## Resolvidos

| ID | Descrição | Resolução | Evidência |
|---|---|---|---|
| BLK-R1 | A Entrega 3 dependia da aprovação do ADR-0012 (AGPL do plugin DICOMweb) | ADR-0012 revisada: sem plugins AGPL, com o DICOMweb implementado no CORE. Ficou só a revisão da distribuição (BLK-07), que não bloqueia o desenvolvimento | `docs/adr/ADR-0012.md` |
| BLK-R2 | O TPM "não verificável" contava como aprovado | Situação própria "não verificável" na validação, no relatório e nas notas da release | Commit `e6920eb`; `tests/test_validation_status.py` |
| BLK-R3 | `filelock` 4.1.1 com 6 alertas no ambiente de build da plataforma | Restrição `filelock>=4.2.1` nos pipelines; a auditoria mostra quem exige o pacote e confere se ele entra no pacote | Commit `91057f3`; resultado do CI no estado do projeto |
