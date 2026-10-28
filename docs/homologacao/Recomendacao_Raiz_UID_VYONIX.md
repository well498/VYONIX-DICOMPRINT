# Recomendação técnica: raiz de UID própria da VYONIX

Situação: recomendação para o futuro. **Não bloqueia o desenvolvimento.** Desde o BKL-10, os UIDs criados pelos
produtos usam `2.25.<UUID>` (PS3.5 §B.2). Essa forma é conforme ao padrão e não depende de raiz registrada.

## 1. Por que ter uma raiz própria

O formato `2.25` já basta para os UIDs de instância. Uma raiz própria agrega três coisas:

- **Identificação do fabricante.** O Implementation Class UID é enviado em toda associação DICOM e gravado no
  File Meta dos arquivos.
  - Hoje ele vem das bibliotecas, sem configuração explícita no Print.
  - Na associação, o pynetdicom envia `1.2.826.0.1.3680043.9.3811.<versão>`.
  - Nos arquivos que o Print grava, o pydicom usa a raiz `1.2.826.0.1.3680043.8.498`.
  - O correto é usar um identificador da VYONIX. Isso deve aparecer na Declaração de Conformidade DICOM.
- **Rastreabilidade.** Um prefixo próprio permite reconhecer, em qualquer PACS, objetos criados pelos produtos
  VYONIX.
- **Exigência de clientes e auditorias.** Alguns integradores pedem a raiz registrada do fabricante.

## 2. Opções para obter a raiz

| Opção | Raiz resultante | Custo e prazo | Avaliação |
|---|---|---|---|
| **IANA Private Enterprise Number (PEN)** | `1.3.6.1.4.1.<n>` | Formulário em https://www.iana.org/assignments/enterprise-numbers/assignment/apply/, por ordem de chegada. Pelo que se sabe, sem custo (confirmar no envio). Prazo de dias a semanas. | **Recomendada.** É usada por muitos fabricantes DICOM, é permanente e é da própria empresa. |
| Registro nacional ou ISO (ex.: ANSI, ABNT ou outro emissor de OID) | `2.16.<país>…` ou `1.2.<país>…` | Pago, com processo formal | Possível, mas sem vantagem técnica sobre o PEN. |
| Sub-raiz cedida por terceiros (ex.: `1.2.826.0.1.3680043.<n>`) | Dentro da raiz do terceiro | Gratuita | Funciona, mas a raiz pertence a outra organização. É o mesmo tipo de dependência corrigido no BKL-10. |
| Continuar só com `2.25.<UUID>` | — | Nenhum | Conforme ao padrão e suficiente para os UIDs de instância. Não identifica o fabricante. |

## 3. Uso proposto depois do registro (exemplo com PEN `n`)

```
1.3.6.1.4.1.n                  raiz VYONIX (nunca usada sozinha como UID)
1.3.6.1.4.1.n.1                DICOM Print
1.3.6.1.4.1.n.1.1.<versão>     Implementation Class UID do Print (ex.: .1.1.1.0.0)
1.3.6.1.4.1.n.2                Plataforma (Core, PACS, RIS)
1.3.6.1.4.1.n.2.1.<versão>     Implementation Class UID da plataforma
1.3.6.1.4.1.n.9                reservado para documentação e testes
```

Regras de uso:

- **UIDs de instância** (estudo, série, SOP, Image Box, sessão de filme): manter `2.25.<UUID>`. Ele é único sem
  coordenação, funciona offline e não exige contador nem identificador de instalação.
  - Alternativa: `raiz.produto.<instalação>.<tipo>.<contador ou tempo>`. Ela exige garantir unicidade entre
    reinstalações e cópias de máquina virtual. Não se recomenda migrar.
- **Implementation Class UID e Implementation Version Name** (ex.: `VYONIX_PRINT_1`): passar a usar a raiz própria
  no Print SCP/SCU, no Storage SCP, no Q/R do Core e no File Meta dos arquivos gravados.
  - É uma mudança pequena: `ae.implementation_class_uid` no pynetdicom e o File Meta ao salvar.
  - Precisa de aprovação própria, por ser visível às modalidades.
- **Nunca reaproveitar UID.**
- **Nunca reescrever UIDs recebidos.**
- **Registrar a árvore** de sub-raízes em documento controlado, com responsável. Nenhum arco é reatribuído depois
  de usado.

## 4. Passos sugeridos

1. O proprietário solicita o PEN em nome da VYONIX. O dado é público: nome da organização e contato.
2. Registrar a árvore acima neste repositório: ADR e Declaração de Conformidade DICOM.
3. Implementar a troca do Implementation Class UID numa branch isolada, com testes de associação. Validar no
   laboratório com as modalidades de teste antes de qualquer versão.
4. Os UIDs `2.25` já gerados continuam válidos para sempre e não precisam de migração.

O módulo central `app/dicom/uids.py` já isola a geração de UIDs. Se no futuro se decidir usar a raiz própria
também nos UIDs de instância, a mudança fica concentrada nesse módulo.
