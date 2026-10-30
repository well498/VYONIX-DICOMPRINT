# Referência — worklist da RadCloud (imagem pública de divulgação), enviada pelo proprietário em 29/10/2026 21:49

**Fonte:** duas fotos de tela, enviadas pelo proprietário, de uma imagem pública de divulgação hospedada em
`framerusercontent.com/images/…` (material do site da RadCloud, com dados fictícios: "Clínica Virtual",
"RADCLOUD …", "DR RADCLOUD"). As fotos não são guardadas no repositório; aqui fica só a descrição.
**Classificação:** DECLARADO PELO FORNECEDOR (imagem de demonstração, não é teste do produto). Nada foi acessado
em área restrita.

## O que a imagem mostra
* Barra superior com 3 itens: **Dashboard**, **Worklist**, **Relatórios ▾** (+ ícone parcialmente visível);
  alternância de tema escuro/claro (ícone de lua). Tema escuro.
* Worklist em tabela com as colunas **Unidade · Paciente · Dt. Estudo · Médico · Status · SLA**, ordenáveis
  (setas em Unidade e Dt. Estudo).
* **Prioridade dentro da coluna Unidade**, como etiqueta colorida sob o nome: *Eletivo* (azul), *Urgência*
  (laranja), *Emergência* (vermelho).
* **Status** como etiqueta colorida curta: *Novo* (apagado), *Laudando* (azul), *Assinado* (verde).
* **SLA** com o prazo-limite (data e hora) e, abaixo, uma **barra de progresso com percentual do prazo consumido**:
  31% (azul), 42% (laranja), **365% (vermelha, prazo estourado)**; quando concluído, a barra dá lugar a
  *Finalizado* (verde).
* Coluna Médico vazia quando o exame ainda não foi atribuído.

## O que isso confirma para o VYONIX (princípios, não cópia)
* Prazo (SLA) visível na própria fila, com indicação **graduada** antes de estourar — já recomendado pela pesquisa
  (Laudos.AI, Pixeon, Telelaudo) e agora com um exemplo visual da RadCloud.
* Prioridade junto do exame, com cor por gravidade; status em etiqueta de uma palavra.
* Poucos itens de navegação para quem lauda (painel, fila, relatórios).

## Situação no VYONIX (primeira leitura; a matriz de oportunidades detalha)
* Prazo/atraso existe no backend e na Central de Exames (atrasos), mas a fila de Laudos não mostra prazo
  restante nem progresso do prazo; prioridade existe em `ris.exam.priority`.
* Proposta VYONIX (a desenhar na Fase D, identidade própria): coluna "Prazo" com **tempo restante** em linguagem
  natural ("vence em 2 h", "atrasado há 1 h 20 min") + indicador discreto de cor por faixa
  (no prazo / atenção / atrasado), com texto além da cor (acessibilidade), e ordenação padrão do médico por
  prioridade e prazo. Percentual consumido pode aparecer como dica, não como elemento principal.
