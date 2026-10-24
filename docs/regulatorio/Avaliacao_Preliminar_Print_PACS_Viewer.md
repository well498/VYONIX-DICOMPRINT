# Avaliação regulatória preliminar — DICOM Print, PACS e Viewer

* **Natureza:** avaliação **documental e preliminar**, feita pela engenharia em 2026-10-23 a partir do texto das
  normas. **Não é parecer regulatório.** Nenhum módulo está regularizado, e nada aqui declara conformidade.
* **Pendência:** BLK-06 em `VYONIX_BLOCKERS.md`. A classe e o caminho de cada módulo precisam de um responsável
  técnico regulatório.

## 1. Normas consultadas (versões vigentes em 23/10/2026)

| Norma | O que diz para este caso | Situação |
|---|---|---|
| RDC 657/2022 (Anvisa) | Define SaMD: software com finalidade de dispositivo médico, que não faz parte do hardware de um dispositivo (art. 2º, VII). Exclui software de bem-estar, software usado **exclusivamente** para gestão administrativa e financeira, e software que trata dados demográficos e epidemiológicos sem finalidade clínica (art. 1º, §2º). **Não exclui** software que apenas guarda ou transmite dados. A classificação segue as regras de classe (art. 4º). Classes I e II são notificadas (art. 10); III e IV são registradas (art. 12). A empresa pode pedir à Anvisa um enquadramento (art. 19) | Vigente. A revisão da norma está na agenda regulatória da Anvisa para 2026–2027 |
| RDC 751/2022 (Anvisa) | Substituiu a RDC 185/2001 desde 1º/03/2023 (arts. 66 e 67). **Regra 11:** software que presta informações usadas em decisões diagnósticas ou terapêuticas é **classe II**; vai para III se a decisão puder levar a uma intervenção cirúrgica ou deterioração grave, e para IV se puder levar à morte ou a dano irreversível. Qualquer outro SaMD é **classe I**. **Regra 17:** dispositivos destinados especificamente a registrar imagens de diagnóstico de raios X são classe II | Vigente; não consta da agenda de revisão 2026–2027 |
| RDC 665/2022 (Anvisa) | Boas Práticas de Fabricação de dispositivos médicos | Vigente. Não reli o texto nesta avaliação; o alcance para cada classe deve ser confirmado pelo especialista |
| LGPD (Lei 13.709/2018) | Dados de saúde são dados sensíveis | Já tratada em parte: dados de paciente fora dos logs e da telemetria; anonimização no License Manager |
| IEC 62304, ISO 14971, IEC 62366-1 | Ciclo de vida do software, gestão de risco e usabilidade, esperados como evidência técnica | Sem documentação formal ainda; há rastreabilidade e testes, mas não há plano de gestão de risco |

## 2. Avaliação por módulo

| Item | VYONIX DICOM Print | VYONIX PACS | VYONIX Viewer |
|---|---|---|---|
| **Finalidade pretendida (proposta, a confirmar)** | Receber imagens DICOM de equipamentos e imprimi-las em papel ou filme, conforme regras configuradas, para documentação e entrega | Receber, guardar, pesquisar e distribuir estudos DICOM entre unidades e sistemas autorizados | Exibir estudos DICOM a profissionais autorizados |
| **Funções com efeito clínico** | Calibração de brilho, contraste e gama, layout e escala física da impressão. Alteram a apresentação da imagem impressa, não os dados DICOM | Integridade e associação correta estudo ↔ paciente (risco de troca de paciente); retenção | Window/level, medições, regiões de interesse, comparação: usadas para ler a imagem |
| **Principais riscos** | Imagem impressa com contraste ou escala errados; impressão no paciente errado; impressão duplicada ou faltante | Estudo associado ao paciente errado; perda ou corrupção de imagens; acesso indevido | Medição errada; imagem apresentada com transformação incorreta; estudo errado na tela |
| **Enquadramento possível** | Depende da finalidade declarada. Se a impressão for usada para diagnóstico, há argumentos para **classe II** (Regra 11, ou Regra 17 para registro de imagens de raios X). Se a finalidade declarada for só documentação e entrega, sem uso diagnóstico, o especialista deve avaliar se fica fora do escopo de SaMD. **Não há exclusão automática** | Se for SaMD, **classe I** pela regra residual da Regra 11, salvo se a finalidade incluir informação para decisão diagnóstica (**classe II**). Guardar e transmitir não está excluído da RDC 657 | **Classe II** é o mais provável para leitura diagnóstica (Regra 11); classe III se as decisões puderem levar a cirurgia. Um viewer "só para consulta, não diagnóstico" precisa dessa limitação declarada e respeitada |
| **Validação necessária** | Impressão física, escala, calibração e qualidade (homologação HF-05 a HF-08); conformidade DICOM com equipamentos reais | Testes de integridade e de reconciliação; desempenho; backup e restauração | Validação de medições e apresentação; usabilidade com radiologistas; comparação com viewer de referência |
| **Obrigações documentais prováveis** | Notificação (classe II) com o dossiê técnico da RDC 657 (art. 10); gestão de risco; manual; rotulagem; rastreabilidade | Idem (classe I ou II) | Idem (classe II) |
| **Pendências** | Definir a finalidade; decidir se a impressão é diagnóstica; plano de gestão de risco | Definir a finalidade; política de retenção por organização | Definir se o uso é diagnóstico; validação de medições |
| **Especialista responsável** | Necessário | Necessário | Necessário |

## 3. O que a engenharia já tem e o que falta

| Evidência esperada | Situação |
|---|---|
| Rastreabilidade de requisitos | `VYONIX_REQUIREMENTS_TRACEABILITY.md` |
| Testes automatizados com evidência | 378 testes; aceitação e validação no Windows (CI) |
| Gestão de configuração e de versões | Git, releases com SHA-256, SBOM |
| Plano e relatório de gestão de risco (ISO 14971) | **Falta** |
| Plano de desenvolvimento de software e classe de segurança (IEC 62304) | **Falta** |
| Arquivo de engenharia de usabilidade (IEC 62366-1) | **Falta**; só há verificações automáticas de contraste e layout |
| Validação clínica e de desempenho | **Falta**: depende da homologação física e de profissionais |
| Declaração de conformidade DICOM | Existe para o Print, só de homologação |

## 4. Recomendação

1. Contratar um responsável técnico regulatório. Isso exige sua aprovação, por ser custo externo.
2. Definir por escrito a finalidade pretendida de cada módulo antes de qualquer venda com função clínica.
3. Considerar o pedido de enquadramento à Anvisa (RDC 657, art. 19) para o Print e o PACS, cujos casos são menos óbvios.
4. A engenharia pode começar já, sem aprovação: rascunho do plano de gestão de risco (ISO 14971) do Print,
   classificação de segurança do software (IEC 62304) e registro de perigos a partir dos riscos acima.

## Fontes

* RDC 657/2022 — texto compilado (Anvisa): https://antigo.anvisa.gov.br/documents/10181/5141677/RDC_657_2022_COMP.pdf/d2da154d-bd76-40ba-87ee-3d9baadb5dd3
* RDC 751/2022 — texto compilado (Anvisa): https://antigo.anvisa.gov.br/documents/10181/5672055/%281%29RDC_751_2022_COMP.pdf/4aef938f-dec2-42b2-8f06-5ec94abfbe31
* Agenda regulatória da Anvisa 2026–2027 (Emergo by UL): https://www.emergobyul.com/news/brazil-anvisa-announces-priorities-2026-2027-year
