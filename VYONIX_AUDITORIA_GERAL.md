# VYONIX Medical Platform — Auditoria geral

* **Data:** 29/10/2026 · **Ramo:** `develop` · **Commit de referência:** `d29d391` (195 commits no ramo)
* **Escopo:** VYONIX Medical Platform (Core, PACS, Viewer, RIS, Telelaudo/Laudos, Administração, DEPLOY, Edge).
  **O VYONIX DICOM Print está excluído** (não analisado, não contabilizado, não modificado).
* **Natureza:** auditoria técnica a partir do repositório; nenhuma funcionalidade nova foi implementada nesta etapa.
  Não é avaliação clínica, regulatória ou jurídica.
* **Documentos:** inventário item a item em [`VYONIX_INVENTARIO_FUNCIONAL.md`](VYONIX_INVENTARIO_FUNCIONAL.md)
  (gerado por `tools/auditoria_inventario.py`), pendências em
  [`VYONIX_PENDENCIAS_PRIORIZADAS.md`](VYONIX_PENDENCIAS_PRIORIZADAS.md), plano em
  [`VYONIX_PLANO_CONCLUSAO.md`](VYONIX_PLANO_CONCLUSAO.md), resumo em [`VYONIX_RESUMO_EXECUTIVO.md`](VYONIX_RESUMO_EXECUTIVO.md).

## 1. Método e fontes de evidência

| Fonte | O que foi conferido |
|---|---|
| Código | `vyonix/` (api, auth, audit, clinical, db, events, licensing, modules, pacs, report, ris, settings, tenancy), `vyonix_deploy/`, `web/src/`, `viewer/`, `installer/` |
| Banco | 26 migrações (`core_0001–0003`, `pacs_0001–0008`, `report_0001–0010`, `ris_0001–0007`); RLS conferido por teste de arquitetura em toda tabela de organização |
| Testes | 281 funções de teste da plataforma (`tests_platform` 244, `tests_deploy` 34, `tests_viewer` 3) |
| CI (commit `bc9cf28`/`d29d391`) | platform run 40896603151: **279 testes, 0 pulados, 0 falhas** (PostgreSQL 17.11 + Orthanc real); viewer run 40896603037 (Chromium + Orthanc); deploy-windows run 40896603020: **34 aprovados, 0 reprovados, 1 não executado** (impressão física, que é do Print); homologação run 40896631587 (instalador de homologação, roteiro 13/13) |
| Continuidade | `VYONIX_PROJECT_STATE.md`, `VYONIX_REQUIREMENTS_TRACEABILITY.md`, `VYONIX_BLOCKERS.md`, `VYONIX_NEXT_ACTION.md`, ADRs |
| Verificações adicionais nesta auditoria | buscas no código por convênios, HL7 de entrada, frases rápidas, revisão, entrega, MPR, criptografia do backup, Patient Root, desativação de usuários (resultados no inventário) |

**Critério de "validada":** código + testes automatizados aprovados no CI com os componentes reais do caminho
(PostgreSQL e/ou Orthanc e/ou Windows). Funcionalidade testada só com dublê de algum componente (ex.: motor em
memória) ficou como **implementada, mas não validada**. Ferramenta disponível no OHIF mas não exercitada nos testes
ficou **não verificada**.

**Limites da evidência:** o CI usa Windows Server 2022 (não Windows 10/11 de mesa), não reinicia a máquina e não tem
equipamentos DICOM nem impressoras reais. Logs e artefatos do CI não são baixáveis deste ambiente (HTTP 403): a
evidência vem das anotações dos check-runs. Nenhum teste prático foi concluído pelo proprietário até esta data.

## 2. Situação por módulo (síntese; detalhes no inventário)

| Módulo | Situação |
|---|---|
| **PACS** | Núcleo sólido e testado com Orthanc real: recepção, armazenamento com SHA-256, índice isolado, DICOMweb, C-FIND/C-MOVE/C-GET (Study Root), nós DICOM, quarentena, backup/restauração, integridade, auditoria. Encaminhamento automático e storage commitment implementados mas testados com motor dublê. Falta: compartilhamento entre instituições, Patient Root, DICOM TLS, exclusão por retenção (bloqueada por política). |
| **Viewer** | OHIF 3.13 aberto e navegado no Chromium com Orthanc real; janela/nível, zoom, girar, inverter e medição verificados. Não verificados: pan, anotações, MPR, desempenho. Não implementados: comparação lado a lado e ferramentas por modalidade. Sem validação clínica de medidas. |
| **RIS** | Pacientes, procedimentos, pedidos, agenda por sala/modalidade, MWL, MPPS, Central de Exames, preparação técnica, fluxo configurável e linha do tempo testados. Faltam convênios, HL7 de entrada (ADT/ORM), tela de histórico do paciente e teste com modalidade real. |
| **Telelaudo** | Fila com escopo por vínculo, distribuição manual/fixa/equilibrada, prioridades, prazos, laudo, adendos, liberação com senha e versões imutáveis testados. Faltam revisão (segunda leitura), entrega ao paciente/solicitante e rede de médicos entre instituições. Assinatura digital bloqueada (BLK-14). |
| **Editor de laudos** | Modelos versionados, importação DOCX, identidade visual, PDF e assinatura manuscrita autorizada testados. O editor é texto simples: sem formatação, sem frases rápidas/presets. |
| **Usuários e permissões** | Completo nos requisitos levantados e testado: papéis e permissões por operação validados no backend, isolamento RLS, login sem escolher instituição, delegação sem escalonamento, MFA, desativação. |
| **Cadastro médico** | Completo exceto modelos pessoais do médico. |
| **Produção médica** | Minha Produção completa (filtros, PDF, CSV, permissões, isolamento); financeiro só como tabela por modalidade. |
| **Administração** | Instituições (nuvem), usuários, unidades, salas, nós DICOM, configurações com histórico, auditoria, monitoramento e menu recolhível testados. Faltam alertas ativos e tela de logs; usabilidade não avaliada com usuários. |
| **Infraestrutura e deploy** | Instalador, serviços, recuperação de falhas, diagnóstico e reparo, atualização e desinstalação validados no Windows do CI, inclusive o acesso pelo IP e a recuperação do banco. Pendentes: confirmação na máquina do proprietário, reinicialização real e Windows 10/11 de mesa. |
| **Arquitetura híbrida (Edge)** | ADR-0014 (proposta) e protótipo com central simulado; **não funcional e desabilitado** (BLK-16). |
| **Segurança e conformidade** | Autenticação, autorização, isolamento, auditoria encadeada, ACL e dependências sem vulnerabilidade conhecida. Parciais: criptografia (DICOM sem TLS; banco, imagens e backup sem cifra própria). Bloqueados: chave de emissão comprometida (BLK-01), LGPD/CFM (BLK-06), ICP-Brasil (BLK-14). Sem teste de intrusão. |

## 3. Atenção especial — instalação Windows e acesso web

| Pergunta | Resposta com evidência |
|---|---|
| A causa raiz foi comprovada? | **Sim.** O assistente abria a pasta Documentos (relato do proprietário + código anterior a `344ab09`): nada era configurado. Contribuintes identificados no código: instalador sem aviso nem diagnóstico, firewall só em redes privada/domínio, `http://` na porta HTTPS. O teste real no Windows ainda revelou outra falha: banco que cai não voltava sozinho (run 40890008726). |
| Foi corrigida? | **Sim** (`344ab09`, `0e0a39a`, `bc9cf28`): abertura do assistente, diagnóstico de inicialização, atalho que verifica antes de abrir, aviso no instalador, regra de firewall do perfil Público só para a sub-rede local, redirecionamento `http://`→`https://`, vigia do banco no Worker e tempo limite de conexão. |
| Foi validada em Windows real? | **Parcialmente.** Validada no Windows Server 2022 do CI (critérios 2.10: diagnóstico sem administrador, acesso pelo IP, redirecionamento, regra Pública, banco derrubado e recuperado, ordem de inicialização). **Não** confirmada na instalação do proprietário, **não** testada com reinicialização real nem em Windows 10/11 de mesa. Por isso continua como **P0** até a confirmação prática. |

## 4. Problemas críticos identificados

1. **Confirmação prática da instalação pendente** (P0): a falha de 28/10 só pode ser dada como resolvida depois de
   reinstalar com o instalador `bc9cf28` numa máquina do proprietário, de preferência Windows 10/11, incluindo
   reiniciar o computador.
2. **Chave de emissão de licenças comprometida** (BLK-01): documentos forjados com ela ainda são aceitos — risco
   comercial e de segurança; depende do proprietário.
3. **Sem assinatura digital de laudos** (BLK-14) e **sem avaliação LGPD/CFM** (BLK-06): impedem qualquer uso clínico.
4. **Sem teste com equipamentos DICOM reais** (BLK-02): MWL, MPPS, C-STORE e storage commitment só com SCU simulado.
5. **Criptografia em repouso e DICOM TLS ausentes**: banco, imagens e backups dependem da proteção do sistema
   operacional (ex.: BitLocker), não documentada como requisito de instalação.
6. **Editor de laudos simples demais para uso diário** (texto sem formatação, sem frases rápidas): limita a adoção.

Defeitos conhecidos abertos: nenhum reproduzível no CI atual. Instabilidades já registradas pertencem ao DICOM Print
(fora do escopo).

## 5. Percentual de conclusão

Calculado em [`VYONIX_INVENTARIO_FUNCIONAL.md`](VYONIX_INVENTARIO_FUNCIONAL.md) com 135 itens e pesos iguais:
**implementação ≈ 78%**, **validação automatizada ≈ 71%** do inventário. **Confiabilidade da estimativa: baixa como
medida de prazo** (itens de esforço muito diferente contam igual) e **nula como prontidão clínica** (nenhum item tem
validação clínica). Serve para comparar módulos: Usuários (100%) e PACS (91%) mais adiantados; Viewer (57%), Segurança
(58%) e Edge (38%) mais atrasados.

## 6. Referências técnicas consideradas

dcm4chee/J4Care SMooTH (`docs/platform/Estudo_Referencias_dcm4chee_J4Care.md`), Orthanc (ADR-0012), OHIF 3.13,
DICOM PS3.4/PS3.18, HL7 v2 e FHIR. Funcionalidades de referência só entraram como requisito quando pedidas pelo
proprietário ou necessárias ao fluxo; as demais aparecem como P3.
