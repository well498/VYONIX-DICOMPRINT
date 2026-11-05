# Evidência 01 — estado após reconexão (05/11/2026 ~11:40)
- Login admin (credencial digitada pelo proprietário) → 200 stage ok.
- /pacs/status: engine Orthanc 1.13.0 configured=true reachable=true, AET VYONIX_PACS porta 4242 (após atalho "Preparar modulos" executado pelo proprietário).
- Índice antes do STOW DEMO: 1 estudo/1 série/8 instâncias — estudo do PROPRIETÁRIO (PatientID 1475, "TC de crânio (sintético)"), declarado fictício por ele; fora do conjunto DEMO, não alterado.
- Usuários: 17 = admin, tecnico-cdi, JoaoVictor (do proprietário, fictício segundo ele) + 14 demo.*
- Pacientes DEMO 15; pedidos O01–O16 status requested; nós PACS 6.
- Falha anterior (08:45): STOW 503 "Armazenamento DICOM não configurado (pacs_orthanc_url)" em 20 envios — instalação nova deixa módulo pacs habilitado sem motor (achado M4-INST-01, P1).
- sessionStorage perdido com o fechamento do app (inventário provisório e senhas iniciais demo) — inventário reconstruído pela API; senhas serão redefinidas pelo admin.
