# VYONIX — Próxima ação executável

* **Atualizado em:** 2026-10-29 · ramo `develop`
* **Último commit local:** ver `git log -1`; CI do lote enviado: platform, viewer, deploy-windows, Windows release.

## Agora
1. **P0 (prioridade máxima):** aguardar a validação presencial do instalador `bc9cf28` com o kit
   `installer/validacao` e o roteiro `docs/homologacao/Roteiro_Validacao_P0_Instalacao.md`; corrigir qualquer falha
   relatada antes de declarar resolvido. Não alterar a instalação atual do proprietário sem autorização.
2. Em paralelo (independente do instalador): editor rico, frases, modelos pessoais e revisão **feitos**; seguir com
   segurança/testes e o bloqueio de associação DICOM simulado (BLK-15, só em ambiente de teste).

## Auditoria geral (29/10/2026)
Ver `VYONIX_RESUMO_EXECUTIVO.md`, `VYONIX_AUDITORIA_GERAL.md`, `VYONIX_INVENTARIO_FUNCIONAL.md`,
`VYONIX_PENDENCIAS_PRIORIZADAS.md` e `VYONIX_PLANO_CONCLUSAO.md`. Próxima ação: Fase P0 do plano (confirmação
prática da instalação) — aguarda o proprietário; sem novas funcionalidades até lá.

## Feito em 29/10
* Correção definitiva da inicialização e do acesso web (`docs/homologacao/Correcao_Inicializacao_Acesso_Web.md`),
  validação no Windows do CI (critérios 2.10) e novo instalador de homologação.
* Storage commitment SCP, encaminhamento de estudos, protótipo Edge Sync (ADR-0014, desabilitado).

## Próximo ciclo (autorizado, sem decisão comercial)
1. Encaminhamento: reenviar imagens que chegam depois do envio concluído.
3. **Receptor HL7 ADT/ORM (MLLP)** para HIS externo.
4. DICOM TLS opcional no Q/R.

## Aguardando o proprietário
* Avaliação prática da homologação (instalador `344ab09`) e relatos de falhas.
* BLK-01: escolher a alternativa (recomendada: separar a plataforma agora, rotacionar o Print depois) — nada de
  destruir/substituir/revogar até nova decisão.
* Visualizadores externos: ligar o Weasis na homologação (e confiar o certificado no computador); decidir sobre o
  Oviyam (proposta de isolamento em `docs/platform/Visualizadores_Weasis_Oviyam.md`).
* Escopo das imagens por vínculo (`pacs/viewer.access = linked`): ligar por padrão muda o comportamento homologado.
* BLK-15 (recusa na associação; simulação aprovada no CI; ativar na instalação só com aprovação específica), BLK-16 (edge → cloud), BLK-14 (ICP-Brasil), BLK-01 (chave de emissão: escolher
  caminho A ou B e autorizar a destruição das cópias — plano em `docs/security/`).
