# VYONIX — Bloqueios

Registro dos impedimentos (Comando Executivo de continuidade, §4). Um bloqueio para só a tarefa afetada; as
"ações que podem continuar" seguem sem esperar.

**Tipos:**
* **Crítico:** impede uma operação por risco de segurança, integridade ou conformidade.
* **Externo:** depende de hardware, ambiente, fornecedor ou acesso.
* **Aprovação:** depende de decisão expressa do responsável.
* **Técnico:** a equipe resolve sozinha.

* **Atualizado em:** 2026-10-24 (01:12, instruções do proprietário)
* **Bloqueios abertos:** 11. **Resolvidos:** 5.

## Abertos

| ID | Descrição | Módulo | Tipo · gravidade | Causa | Depende de | Quem resolve | Aprovação? | O que continua | Condição de desbloqueio |
|---|---|---|---|---|---|---|---|---|---|
| BLK-01 | Chave de emissão `vyx-2026-01` comprometida: documentos forjados com ela ainda são aceitos | License Manager, Print, Core, License Server | Crítico · alto | Chave gerada no ambiente de desenvolvimento; frase-senha enviada pelo chat (INC-2026-10-23) | Chave nova gerada pelo fornecedor e lista de documentos legítimos exportada | Fornecedor (passos 2–3) e desenvolvimento (passo 4) | Sim, para publicar a atualização e avisar os clientes | Mecanismo de restrição pronto e testado; todo o resto do projeto | `RESTRICTED_KEYS` preenchido com a lista exportada e a chave nova em `PUBLIC_KEYS`, numa release distribuída |
| BLK-02 | Nenhum teste com equipamento DICOM real | Print | Externo · alto | O CI só tem SCU simulado | Equipamento ou simulador de fabricante, operador | Responsável e técnico de campo | Não | Testes simulados e o resto do desenvolvimento | Roteiro HF-03 executado e registrado (`docs/homologacao/`) |
| BLK-03 | Nenhuma impressão em impressora física | Print | Externo · alto | O CI só tem "Microsoft Print to PDF" | Impressora (papel e, se houver, filme) | Responsável | Não | Impressão para PDF, testes de layout | Roteiros HF-05 a HF-07 executados |
| BLK-04 | Nenhum teste em Windows 10 ou 11 limpo | Print, DEPLOY | Externo · alto | O CI usa Windows Server 2022 | Máquinas ou VMs com Windows 10 1809+ e 11 | Responsável | Não | Testes no Server 2022 | Roteiros HF-01 e HF-02 executados |
| BLK-05 | Publicação de releases | Print, License Manager | Aprovação · médio | A publicação distribui software a terceiros | Sua decisão, por release | Responsável | **Sim** | Builds de teste no CI (artefatos) | Aprovação registrada no estado do projeto |
| BLK-06 | Finalidade pretendida e enquadramento regulatório indefinidos | Todos | Externo · alto | Exige especialista e decisão de negócio | Responsável técnico regulatório | Responsável | **Sim** (custo e escopo) | Avaliação documental preliminar (`docs/regulatorio/`) | Parecer de especialista sobre a classe e o caminho de cada módulo |
| BLK-07 | Revisão jurídica da distribuição do Orthanc (GPLv3) com o produto comercial | PACS | Aprovação · médio | Obrigação de licença | Advogado | Responsável | **Sim** (custo externo) | Desenvolvimento e testes internos do PACS (ADR-0012); o pacote de CI já leva o `Orthanc.exe` oficial com LEIA-ME de origem, indicação do código-fonte e texto da GPLv3 | Parecer favorável ou decisão de outro motor |
| BLK-08 | Assinatura de código dos instaladores | Todos | Aprovação · médio | Requer certificado pago | Compra do certificado | Responsável | **Sim** (custo) | Builds sem assinatura | Certificado disponível como segredo do CI |
| BLK-09 | Credenciais do sandbox do Banco Inter | Comercial | Externo · médio | Sem acesso ao sandbox | Credenciais do Inter | Responsável | Não | Testes com a reprodução local da API | Teste no sandbox registrado |
| BLK-12 | Recuperação da senha administrativa do License Manager adiada por decisão do proprietário (24/10/2026). Proibido nesta fase: redefinir senhas, excluir contas ou alterar credenciais | License Manager | Aprovação · médio | Decisão do proprietário | Liberação expressa do proprietário | Proprietário | **Sim** | Todo o desenvolvimento independente; a ferramenta da rotação de chave (passo 4) fica pronta para quando o acesso for retomado | Autorização expressa do proprietário |
| BLK-13 | Ensaios em campo (equipamentos e clínicas reais) | Print, PACS, Viewer | Aprovação · alto | Decisão do proprietário (24/10/2026): testes do DICOM Print só no laboratório offline | Autorização expressa | Proprietário | **Sim** | Testes automatizados e homologação no laboratório offline | Autorização expressa do proprietário para cada ensaio |

## Resolvidos

| ID | Descrição | Resolução | Evidência |
|---|---|---|---|
| BLK-R1 | A Entrega 3 dependia da aprovação do ADR-0012 (AGPL do plugin DICOMweb) | ADR-0012 revisada: sem plugins AGPL, com o DICOMweb implementado no CORE. Ficou só a revisão da distribuição (BLK-07), que não bloqueia o desenvolvimento | `docs/adr/ADR-0012.md` |
| BLK-R2 | O TPM "não verificável" contava como aprovado | Situação própria "não verificável" na validação, no relatório e nas notas da release | Commit `e6920eb`; `tests/test_validation_status.py` |
| BLK-R3 | `filelock` 4.1.1 com 6 alertas no ambiente de build da plataforma | Restrição `filelock>=4.2.1` nos pipelines; a auditoria mostra quem exige o pacote e confere se ele entra no pacote | Commit `91057f3`. CI: o `filelock` 4.1.1 vinha do `pipx` da imagem do runner e **não** está no pacote distribuído (run 40057755638); atualizado também no ambiente de build (commit `53711c9`) |
| BLK-R4 | O OHIF não podia ser compilado no ambiente de desenvolvimento (registro npm inacessível) | Compilação do OHIF v3.13.13 no CI (`tools/build_viewer.sh`), usada pelo `viewer.yml` e pelo `deploy-windows.yml` | viewer run 40059704370 |
| BLK-R5 | Recepção por C-STORE no modo cloud não sabia a organização de destino | Rotas de AE Title por organização (únicas no servidor, RLS); distribuição pelo `CalledAET` registrado pelo motor; sem rota ou sem licença = quarentena | `tests_platform/test_pacs.py::CloudRouting`; `test_pacs_orthanc.py` (origem com o Orthanc real, CI) |
