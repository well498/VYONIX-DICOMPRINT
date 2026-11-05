# A08 — Validação do inventário (Missão 4, FASE 4)

Fonte: export real da instância (0.3.1, edge, homologação), gerado em 2026-11-05T14:49:30Z pelo coordenador
logado como admin (somente GET):
/tmp/claude-0/-home-claude/642eff65-37eb-5d06-92b3-e92c60125a68/scratchpad/m4/export/VYONIX_DEMO_EXPORT_20261105.json
(sha256 c146a555…42a9e).
Script: /tmp/claude-0/-home-claude/642eff65-37eb-5d06-92b3-e92c60125a68/scratchpad/m4/export/a08_inventario.py
(rodado com `python3 -I a08_inventario.py`, rc=0)
Saída: /tmp/claude-0/-home-claude/642eff65-37eb-5d06-92b3-e92c60125a68/scratchpad/m4/export/inventario.json
(sha256 f933aa77…eebb).

Tipo de evidência: **análise do export da API da instância do proprietário**. Não tive acesso ao banco nem à
instância. Por isso o que só o SQL confere (Q10/Q20 de A08.md, por exemplo `pacs.studies.clinical_study_id` e
`report_starts`) continua A EXECUTAR.

## 1. Integridade relacional (export × regras)
O script fez 378 verificações e todas passaram. **Não encontrou nenhum órfão nem referência quebrada.**

| Regra | Resultado |
|---|---|
| pedido → paciente existente | 17/17 |
| pedido → procedimento existente | 17/17 |
| estudo DEMO → paciente | 20/20 |
| estudo DEMO → pedido (exceto anteriores A01–A03, que não têm pedido por desenho) | 17/17; A01–A03 sem pedido (3/3, esperado) |
| estudo × pedido com o mesmo paciente / `reconciled_at` preenchido | 17/17 / 17/17 |
| estudo clínico ↔ QIDO (StudyInstanceUID) e PatientID = identificador DICOM do paciente | 20/20 / 20/20 |
| QIDO 00201206 = séries listadas; QIDO 00201208 = Σ 00201209 das séries | 20/20 / 20/20 |
| `pacs_status.index` (21/35/78) = Σ QIDO (21 estudos, 35 séries, 78 instâncias) | confere |
| laudo → estudo; laudo.order_id = estudo.order_id; nº de versões = `version`; laudo final tem versão | 10/10 em cada |
| médico → usuário; vínculo → unidade existente | 3/3; 3/3 |
| papel → unidade existente; papel → perfil existente | 18/18; 18/18 (todos os usuários) |
| nó DICOM → unidade existente | 7/7 |
| modelo → procedimento/unidade; agendamento → pedido | 1/1; 2/2 |
| auditoria: `audit/verify` ok=true, broken=[]; seq 1–479 sem lacuna | ok |
| auditoria × dados: `pacs.instance.store`=78=instâncias; `study.register`=21=estudos; finalize 7 + adendo 2 = 9 versões | confere |
| criação auditada (primeiro evento por target_id): usuários 17, pacientes 15, pedidos 17, estudos 21, médicos 3, nós 7, unidades DEMO 2 | todos com evento |

## 2. Contagens por entidade (estado real em 14:49Z)
| Entidade | Total | DEMO | Proprietário (só listado) |
|---|---|---|---|
| Unidades | 3 | 2 (DEMO Matriz, DEMO Unidade Satélite) | 1 ("Unidade principal") |
| Usuários | 17 | 14 (todos com `must_change=false`: troca do 1º acesso feita) | 3 (admin, tecnico-cdi, JoaoVictor) |
| Atribuições de papel DEMO | 15 | 13×1 + demo.multi×2 | — |
| Perfis | 9 | 4 modelos ativados (coordenador_cdi, gestor_telelaudos, suporte_tecnico, financeiro) | 5 do sistema |
| Médicos / vínculos | 3 / 3 | Ana e Carla: organização inteira; Bruno: só Satélite | — |
| Procedimentos | 6 | 6 | — |
| Pacientes / identificadores | 15 / 30 | 15 / 30 | — |
| Pedidos | 17 | 16 (O01–O16) + 1 (P08, accession 261105689112) | — |
| Agendamentos RIS | 2 | O01, O16 | — |
| Estudos | 21 | 20 (O01–O16, A01–A03, X08) | 1 (PatientID 1475) |
| Séries / instâncias (QIDO) | 35 / 78 | 34 / 70 | 1 / 8 |
| Nós DICOM | 7 | 6 simulados + 1 C-ECHO ao próprio motor | — |
| Laudos | 11 | 10 (7 final, 3 rascunho) e 9 versões liberadas | 1 rascunho (JoaoVictor) |
| Modelos / frases visíveis ao admin | 1 / 1 | + 1 modelo pessoal (T01) e 1 frase pessoal (F01), que só aparecem na auditoria | — |
| Configurações | 12 | todas com row_version 0 (padrão) | — |
| Auditoria | 479 eventos | — | — |
| Testes do log | 318 | 313 ok e 5 falhas; 10 marcados ok com resultado diferente do esperado, justificado em `nota` | — |

## 3. Divergências inventário (CONTEXTO/ids) × banco real
Nenhuma divergência é corrupção de dados. Todas se explicam pelos testes do log:
1. **O11 prioridade urgent → stat.** Mudança feita de propósito (T-REP-F4a/F4b: o médico pede, o técnico altera).
2. **Situação dos pedidos.** O01–O16 saíram de `requested`: 7 estão `completed` (O01, O03, O05, O07, O11, O13, O14 = laudos finais) e 9 `in_progress`. É a evolução normal do fluxo.
3. **P08 "sem pedido" agora tem pedido** (261105689112). Foi criado para a conciliação manual do X08 (T-PACS-17a/17b). Os testes negativos 17n e 17c deram 409, como esperado. A aba Pacientes registra P08 com `grupo = "sem pedido (inicial)"`.
4. **O16 "sem estudo" (02_stow.md) agora tem estudo** (1 série, 2 instâncias), recebido com o UID do agendamento MWL (T-PACS-O16, T-RIS-MWL-O16).
5. **O agendamento de O01 aponta um StudyInstanceUID que não existe no índice** (2.25.3120…). O O01 foi agendado depois do STOW e o estudo real foi conciliado pelo accession. P3, sem órfão porque `schedule.order_id` é válido.
6. **No estudo X08 o accession (DEMO2611X08) é diferente do pedido (261105689112).** A conciliação manual mantém o accession do DICOM. Esperado; documentar.
7. **Unidade: 21/21 estudos estão sem `site_id`**, tanto na Central de Exames quanto na fila de laudos. Isso confirma A08-M4-01 (P1). A unidade dos pedidos não é persistida (A08-M4-02, P2).

## 4. Observações para a classificação das falhas (código 0.3.1)
- **T-UNI-MED02-04** (Dr. Bruno abriu metadata do O08, recebeu 200 e o esperado era 403). Com a configuração exportada `pacs/viewer.access = "organization"`, o código não restringe o visualizador (vyonix/pacs/viewing.py:47). Mesmo com `linked`, o O08 está sem unidade (A08-M4-01). Classificar como requisito não implementado ou configuração, não como corrupção.
- **Modelo da instituição criado por médico** (T-TPL-04, b8a69745, ainda rascunho). Está registrado na aba Templates com observação. A decisão fica com A03/A04.
- **Laudo do proprietário (58c9f831) no estudo 1475.** Foi aberto e iniciado por JoaoVictor, que tem papel `medico` na Unidade principal mas **não tem cadastro de médico**. Só listado; não alterar.

## 5. inventario.json (estrutura e autoverificação)
- `meta.linhas_por_aba`: Instituições 1, Regiões 1 (NÃO IMPLEMENTADO), Unidades 3, Usuários 17, Perfis 9, Pacientes 15, Médicos 3, Equipamentos 7, Gateways 1 (NÃO IMPLEMENTADO), Exames 17, Estudos DICOM 21, Laudos 11, Templates 2, Frases rápidas 2, Configurações 12, Testes 318, Falhas 5, Pendências 5, Evidências 5, Referências de credenciais 17.
- Todas as linhas têm as 12 colunas comuns na ordem pedida, seguidas das colunas específicas da aba.
- Status só da lista permitida. Registros do proprietário ficam com `escopo = PROPRIETARIO` e status A EXECUTAR. Eles **não** são aprovados pela missão.
- Autoverificação do script: `ok`.
  - `identificador_demo` único: repetições do log ganham sufixo `#n`, e os estudos usam o prefixo `E-`.
  - `id_real` é UUID (exceto em Configurações).
  - **Nenhum e-mail** e nenhum campo de senha ou token.
  - Nome de exibição, e-mail e último acesso de admin, tecnico-cdi e JoaoVictor foram omitidos. O estudo 1475 e o laudo do proprietário não trazem nome de paciente nem conteúdo.
- Credenciais: nenhuma senha. A referência é "Redefinir pelo admin em Usuários e papéis → Redefinir senha (troca obrigatória no 1º acesso)", com `troca_obrigatoria_confirmada` derivado de `must_change=false`.
- Instituição: o id real vem do evento `organization.create` da auditoria, porque o export não inclui `GET /organization`.
- **Atenção:** o export bruto contém o e-mail de um usuário do proprietário. Não redistribuir esse arquivo. O inventário derivado não contém e-mail.

## 6. Não verificado
- Banco direto (SQL Q10/Q20). Itens que a API não mostra: `clinical_study_id`, `report_starts.origin`, `physician_links.created_by`.
- Conteúdo de T01 e F01 (pessoais). Precisa de login como demo.medico.01.
- Integridade dos arquivos DICOM no Orthanc além do índice (SHA-256 por instância só aparece no banco).
- Se as 10 linhas "ok com divergência anotada" estão de acordo com o requisito. Isso cabe ao coordenador e a A03/A04.
