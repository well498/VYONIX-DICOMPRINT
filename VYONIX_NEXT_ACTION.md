# VYONIX — Próxima ação executável

* **Atualizado em:** 2026-10-28 (noite) · ramo `develop`
* **Último commit local:** ver `git log -1`; CI do lote enviado: platform, viewer, deploy-windows, Windows release.

## Agora
1. Conferir o CI do lote (platform com Orthanc real inclui `test_reception_only_from_registered_equipment`).
2. Corrigir o que falhar e reenviar sem cancelar execuções em andamento.

## Próximo ciclo (autorizado, sem decisão comercial)
1. Encaminhamento: reenviar imagens que chegam depois do envio concluído.
2. **Storage commitment SCP** no Q/R do Core respondendo pelo índice (sem mudar o Orthanc).
3. **Receptor HL7 ADT/ORM (MLLP)** para HIS externo.
4. DICOM TLS opcional no Q/R.

## Aguardando o proprietário
* Avaliação prática da homologação (instalador `344ab09`) e relatos de falhas.
* BLK-15 (recusa na associação), BLK-16 (edge → cloud), BLK-14 (ICP-Brasil), BLK-01 (chave de emissão).
