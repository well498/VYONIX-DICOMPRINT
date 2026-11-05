# Evidência 02 — STOW-RS sintético (05/11/2026 ~11:45)
- 19 estudos DEMO enviados via POST /api/v1/pacs/dicomweb/studies: O01–O15 (2 séries x 2 instâncias; O10 MG 1x4), anteriores A01 (P04 CT 2024-03-10), A02 (P04 CR 2025-01-20), A03 (P01 US 2025-08-15), X08 (P08 US sem pedido). Todos HTTP 200.
- O16 intencionalmente sem estudo (cenário agendamento/MWL antes do exame).
- Duplicidade: reenvio da 1ª instância de O01 → HTTP 200 com aviso 00081196=45063 (0xB007), sem nova cópia.
- /pacs/status depois: studies 20 (19 DEMO + 1 do proprietário), series 34, instances 76, bytes 474984. Conta confere: 8 (proprietário) + 56 + 4 (MG) + 8 (anteriores/X08) = 76.
- UIDs completos: 02_stow_uids.json
- Conciliação (GET /ris/prep?accession=…): os 19 estudos aparecem em stage "received", com paciente correto e prioridade herdada do pedido (O03 stat; O05/O09/O11 urgent) → conciliação automática por accession funcionou para O01–O15. Pedido O01 passou de "requested" para "in_progress".
- site_id = null em TODOS os estudos → confirma F1 (P1): estudo recebido pelo PACS fica sem unidade.
