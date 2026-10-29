# VYONIX — Próxima ação executável

* **Atualizado em:** 2026-10-29 · ramo `develop`
* **Último commit local:** ver `git log -1`; CI do lote enviado: platform, viewer, deploy-windows, Windows release.

## Agora
1. Conferir o CI do lote (platform com Orthanc real inclui `test_reception_only_from_registered_equipment`).
2. Corrigir o que falhar e reenviar sem cancelar execuções em andamento.

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
* BLK-15 (recusa na associação), BLK-16 (edge → cloud), BLK-14 (ICP-Brasil), BLK-01 (chave de emissão).
