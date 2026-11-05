-- VYONIX-DEMO-20261105 — conferência SOMENTE LEITURA (0.3.1). Nenhuma instrução altera dados.
\set ON_ERROR_STOP on
SET default_transaction_read_only = on;
SET statement_timeout = '30s';
-- Se conectar com o papel do aplicativo (<prefixo>_app, NOBYPASSRLS), descomente e informe o id da organização:
-- SELECT set_config('vyonix.tenant_id', '<id da organização de GET /organization>', false);

\echo '== Q00 organização(ões) e conferência de modo somente leitura'
SELECT current_setting('transaction_read_only') AS somente_leitura, current_user AS papel;
SELECT id, code, name, kind, active FROM tenancy.organizations ORDER BY created_at;

\echo '== Q01 contagens por tag DEMO'
SELECT 'unidades' AS entidade, count(*) FROM tenancy.sites WHERE name ILIKE 'DEMO %'
UNION ALL SELECT 'usuarios demo.*', count(*) FROM auth.users WHERE lower(username) LIKE 'demo.%'
UNION ALL SELECT 'atribuicoes de papel (demo.*)', count(*) FROM auth.user_roles ur JOIN auth.users u ON u.id = ur.user_id
          WHERE lower(u.username) LIKE 'demo.%'
UNION ALL SELECT 'papeis de modelo ativados', count(*) FROM auth.roles
          WHERE code IN ('coordenador_cdi','gestor_telelaudos','suporte_tecnico','financeiro')
UNION ALL SELECT 'medicos DEMO', count(*) FROM report.physicians WHERE full_name ILIKE '%DEMO%'
UNION ALL SELECT 'vinculos de medicos DEMO', count(*) FROM report.physician_links l JOIN report.physicians p ON p.id = l.physician_id
          WHERE p.full_name ILIKE '%DEMO%'
UNION ALL SELECT 'procedimentos DEMO-*', count(*) FROM clinical.procedures WHERE code LIKE 'DEMO-%'
UNION ALL SELECT 'pacientes DEMO (por identificador)', count(DISTINCT patient_id) FROM clinical.patient_identifiers
          WHERE value LIKE 'DEMO-P%'
UNION ALL SELECT 'identificadores DEMO', count(*) FROM clinical.patient_identifiers WHERE value LIKE 'DEMO-P%'
UNION ALL SELECT 'pedidos DEMO2611*', count(*) FROM clinical.orders WHERE accession LIKE 'DEMO2611%'
UNION ALL SELECT 'agendamentos RIS de pedidos DEMO', count(*) FROM ris.schedules sc JOIN clinical.orders o ON o.id = sc.order_id
          WHERE o.accession LIKE 'DEMO2611%'
UNION ALL SELECT 'nos DICOM simulados', count(*) FROM pacs.dicom_nodes WHERE description ILIKE '%SIMULADO%'
UNION ALL SELECT 'estudos clinicos de pacientes DEMO', count(*) FROM clinical.studies st
          WHERE st.patient_id IN (SELECT patient_id FROM clinical.patient_identifiers WHERE value LIKE 'DEMO-P%')
UNION ALL SELECT 'estudos PACS (PatientID DEMO-P*)', count(*) FROM pacs.studies WHERE patient_id LIKE 'DEMO-P%'
UNION ALL SELECT 'series PACS DEMO', count(*) FROM pacs.series se JOIN pacs.studies ps ON ps.id = se.study_id
          WHERE ps.patient_id LIKE 'DEMO-P%'
UNION ALL SELECT 'instancias PACS DEMO', count(*) FROM pacs.instances i JOIN pacs.studies ps ON ps.id = i.study_id
          WHERE ps.patient_id LIKE 'DEMO-P%'
UNION ALL SELECT 'laudos de estudos DEMO', count(*) FROM report.reports r JOIN clinical.studies st ON st.id = r.study_id
          JOIN clinical.patient_identifiers pi ON pi.patient_id = st.patient_id AND pi.value LIKE 'DEMO-P%' AND pi.issuer = 'DICOM'
UNION ALL SELECT 'versoes liberadas DEMO', count(*) FROM report.report_versions v JOIN report.reports r ON r.id = v.report_id
          JOIN clinical.studies st ON st.id = r.study_id
          JOIN clinical.patient_identifiers pi ON pi.patient_id = st.patient_id AND pi.value LIKE 'DEMO-P%' AND pi.issuer = 'DICOM'
UNION ALL SELECT 'inicios de laudo (report_starts) DEMO', count(*) FROM report.report_starts rs JOIN clinical.studies st ON st.id = rs.study_id
          JOIN clinical.patient_identifiers pi ON pi.patient_id = st.patient_id AND pi.value LIKE 'DEMO-P%' AND pi.issuer = 'DICOM'
UNION ALL SELECT 'modelos de laudo DEMO', count(*) FROM report.templates WHERE name ILIKE '%DEMO%'
UNION ALL SELECT 'frases DEMO', count(*) FROM report.phrases WHERE title ILIKE '%DEMO%'
UNION ALL SELECT 'auditoria por usuarios demo.*', count(*) FROM audit.audit_log WHERE lower(actor) LIKE 'demo.%'
ORDER BY 1;

\echo '== Q02 pedidos x estudos x laudos (um por pedido DEMO)'
SELECT o.accession, o.priority, o.status AS pedido, pr.code AS procedimento,
       (SELECT pi.value FROM clinical.patient_identifiers pi WHERE pi.patient_id = o.patient_id AND pi.issuer = 'DICOM' LIMIT 1) AS paciente,
       st.id AS estudo_clinico, st.site_id, st.reconciled_at IS NOT NULL AS conciliado,
       ps.id AS estudo_pacs, (SELECT count(*) FROM pacs.instances i WHERE i.study_id = ps.id) AS instancias,
       r.status AS laudo, r.version AS versoes
FROM clinical.orders o
LEFT JOIN clinical.procedures pr ON pr.id = o.procedure_id
LEFT JOIN clinical.studies st ON st.order_id = o.id
LEFT JOIN pacs.studies ps ON ps.clinical_study_id = st.id
LEFT JOIN report.reports r ON r.study_id = st.id
WHERE o.accession LIKE 'DEMO2611%'
ORDER BY o.accession;

\echo '== Q10 ORFAOS / INCONSISTENCIAS (esperado: 0 linhas em cada, salvo nota)'
\echo '-- Q10a estudo clinico sem paciente'
SELECT id, study_instance_uid, accession, created_at FROM clinical.studies WHERE patient_id IS NULL;
\echo '-- Q10b estudo PACS sem estudo clinico (indice nao registrado)'
SELECT id, study_uid, patient_id, accession FROM pacs.studies WHERE clinical_study_id IS NULL;
\echo '-- Q10c estudo PACS cujo PatientID nao tem identificador no cadastro'
SELECT ps.id, ps.study_uid, ps.patient_id FROM pacs.studies ps
WHERE NOT EXISTS (SELECT 1 FROM clinical.patient_identifiers pi WHERE pi.value = ps.patient_id);
\echo '-- Q10d serie sem instancia / estudo PACS sem serie'
SELECT 'serie' AS tipo, se.id FROM pacs.series se WHERE NOT EXISTS (SELECT 1 FROM pacs.instances i WHERE i.series_id = se.id)
UNION ALL SELECT 'estudo', ps.id FROM pacs.studies ps WHERE NOT EXISTS (SELECT 1 FROM pacs.series se WHERE se.study_id = ps.id);
\echo '-- Q10e instancia cujo study_id difere do estudo da serie'
SELECT i.id, i.sop_uid FROM pacs.instances i JOIN pacs.series se ON se.id = i.series_id WHERE se.study_id <> i.study_id;
\echo '-- Q10f laudo sem estudo / laudo com pedido diferente do pedido do estudo'
SELECT r.id, r.study_id, 'sem estudo' AS problema FROM report.reports r LEFT JOIN clinical.studies st ON st.id = r.study_id WHERE st.id IS NULL
UNION ALL
SELECT r.id, r.study_id, 'pedido divergente' FROM report.reports r JOIN clinical.studies st ON st.id = r.study_id
WHERE r.order_id IS NOT NULL AND st.order_id IS DISTINCT FROM r.order_id;
\echo '-- Q10g laudo final sem versao liberada / numero de versoes divergente'
SELECT r.id, r.status, r.version, count(v.id) AS versoes FROM report.reports r
LEFT JOIN report.report_versions v ON v.report_id = r.id
GROUP BY r.id HAVING (r.status = 'final' AND count(v.id) = 0) OR count(v.id) <> r.version;
\echo '-- Q10h estudo conciliado cujo paciente difere do paciente do pedido'
SELECT st.id, st.accession, st.patient_id, o.patient_id AS paciente_pedido FROM clinical.studies st JOIN clinical.orders o ON o.id = st.order_id
WHERE st.patient_id IS DISTINCT FROM o.patient_id;
\echo '-- Q10i accession do estudo igual a um pedido mas nao conciliado'
SELECT st.id, st.accession FROM clinical.studies st JOIN clinical.orders o ON o.accession = st.accession AND o.tenant_id = st.tenant_id
WHERE st.order_id IS NULL;
\echo '-- Q10j papel com unidade inexistente ou inativa / papel inexistente / usuario inexistente'
SELECT ur.id, u.username, ur.site_id,
       CASE WHEN ur.site_id IS NOT NULL AND s.id IS NULL THEN 'unidade inexistente'
            WHEN s.active IS FALSE THEN 'unidade inativa'
            WHEN r.id IS NULL THEN 'papel inexistente' ELSE 'usuario inexistente' END AS problema
FROM auth.user_roles ur LEFT JOIN auth.users u ON u.id = ur.user_id LEFT JOIN auth.roles r ON r.id = ur.role_id
LEFT JOIN tenancy.sites s ON s.id = ur.site_id
WHERE (ur.site_id IS NOT NULL AND (s.id IS NULL OR s.active IS FALSE)) OR r.id IS NULL OR u.id IS NULL;
\echo '-- Q10k vinculo de medico / no DICOM / modelo com unidade inexistente (no DICOM nao tem FK)'
SELECT 'vinculo_medico' AS origem, l.id, l.site_id FROM report.physician_links l
  WHERE l.site_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM tenancy.sites s WHERE s.id = l.site_id)
UNION ALL SELECT 'no_dicom', n.id, n.site_id FROM pacs.dicom_nodes n
  WHERE n.site_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM tenancy.sites s WHERE s.id = n.site_id)
UNION ALL SELECT 'modelo_laudo', t.id, t.site_id FROM report.templates t
  WHERE t.site_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM tenancy.sites s WHERE s.id = t.site_id);
\echo '-- Q10l medico sem usuario, usuario inativo ou sem vinculo vigente'
SELECT p.full_name, u.username, u.active AS usuario_ativo,
       (SELECT count(*) FROM report.physician_links l WHERE l.physician_id = p.id AND l.valid_from <= current_date
          AND (l.valid_to IS NULL OR l.valid_to >= current_date)) AS vinculos_vigentes
FROM report.physicians p LEFT JOIN auth.users u ON u.id = p.user_id
WHERE u.id IS NULL OR u.active IS FALSE OR NOT EXISTS (SELECT 1 FROM report.physician_links l WHERE l.physician_id = p.id
      AND l.valid_from <= current_date AND (l.valid_to IS NULL OR l.valid_to >= current_date));
\echo '-- Q10m inicio de laudo sem laudo / atribuicao aberta duplicada'
SELECT 'start_sem_laudo' AS problema, rs.study_id::text AS ref FROM report.report_starts rs
  WHERE rs.report_id IS NULL OR NOT EXISTS (SELECT 1 FROM report.reports r WHERE r.id = rs.report_id)
UNION ALL SELECT 'atribuicao_aberta_duplicada', a.study_id::text FROM report.assignments a WHERE a.status = 'open'
  GROUP BY a.study_id HAVING count(*) > 1;
\echo '-- Q10n tenant divergente entre registro e registro referenciado (deve ser 0)'
SELECT 'pedido x paciente' AS rel, count(*) FROM clinical.orders o JOIN clinical.patients p ON p.id = o.patient_id WHERE o.tenant_id <> p.tenant_id
UNION ALL SELECT 'estudo x pedido', count(*) FROM clinical.studies st JOIN clinical.orders o ON o.id = st.order_id WHERE st.tenant_id <> o.tenant_id
UNION ALL SELECT 'laudo x estudo', count(*) FROM report.reports r JOIN clinical.studies st ON st.id = r.study_id WHERE r.tenant_id <> st.tenant_id
UNION ALL SELECT 'pacs x clinico', count(*) FROM pacs.studies ps JOIN clinical.studies st ON st.id = ps.clinical_study_id WHERE ps.tenant_id <> st.tenant_id
UNION ALL SELECT 'papel x usuario', count(*) FROM auth.user_roles ur JOIN auth.users u ON u.id = ur.user_id WHERE ur.tenant_id <> u.tenant_id
UNION ALL SELECT 'papel x unidade', count(*) FROM auth.user_roles ur JOIN tenancy.sites s ON s.id = ur.site_id WHERE ur.tenant_id <> s.tenant_id;
\echo '-- Q10o pedido DEMO sem estudo (esperado: os pedidos ainda sem envio DICOM)'
SELECT o.accession, o.status FROM clinical.orders o WHERE o.accession LIKE 'DEMO2611%'
  AND NOT EXISTS (SELECT 1 FROM clinical.studies st WHERE st.order_id = o.id) ORDER BY 1;
\echo '-- Q10p paciente DEMO sem pedido (esperado: somente DEMO-P08)'
SELECT DISTINCT pi.value FROM clinical.patient_identifiers pi WHERE pi.issuer = 'DICOM' AND pi.value LIKE 'DEMO-P%'
  AND NOT EXISTS (SELECT 1 FROM clinical.orders o WHERE o.patient_id = pi.patient_id) ORDER BY 1;

\echo '== Q20 ISOLAMENTO POR UNIDADE'
\echo '-- Q20a papeis por usuario demo e unidade (NULL = todas as unidades)'
SELECT u.username, r.code AS papel, coalesce(s.name, '(todas as unidades)') AS unidade
FROM auth.user_roles ur JOIN auth.users u ON u.id = ur.user_id JOIN auth.roles r ON r.id = ur.role_id
LEFT JOIN tenancy.sites s ON s.id = ur.site_id
WHERE lower(u.username) LIKE 'demo.%' ORDER BY u.username, r.code;
\echo '-- Q20b vinculos de medicos por unidade e vigencia'
SELECT p.full_name, p.crm || '/' || p.crm_uf AS crm, u.username, coalesce(s.name, '(organizacao inteira)') AS unidade,
       l.valid_from, l.valid_to
FROM report.physicians p JOIN auth.users u ON u.id = p.user_id
LEFT JOIN report.physician_links l ON l.physician_id = p.id LEFT JOIN tenancy.sites s ON s.id = l.site_id
ORDER BY p.full_name, l.valid_from;
\echo '-- Q20c estudos clinicos por unidade (0.3.1: o recebimento DICOM nao grava unidade -> espera-se tudo em "(sem unidade)")'
SELECT coalesce(s.name, '(sem unidade)') AS unidade, count(*) FROM clinical.studies st
LEFT JOIN tenancy.sites s ON s.id = st.site_id GROUP BY 1 ORDER BY 1;
\echo '-- Q20d nos DICOM por unidade'
SELECT coalesce(s.name, '(sem unidade)') AS unidade, n.ae_title, n.modality, n.enabled, n.can_store, n.can_query, n.can_receive
FROM pacs.dicom_nodes n LEFT JOIN tenancy.sites s ON s.id = n.site_id ORDER BY 1, 2;
\echo '-- Q20e atribuicoes abertas cuja unidade do exame nao e coberta por vinculo vigente do medico'
SELECT a.study_id, p.full_name, st.site_id FROM report.assignments a
JOIN report.physicians p ON p.id = a.physician_id JOIN clinical.studies st ON st.id = a.study_id
WHERE a.status = 'open' AND NOT EXISTS (
  SELECT 1 FROM report.physician_links l WHERE l.physician_id = p.id AND l.valid_from <= current_date
    AND (l.valid_to IS NULL OR l.valid_to >= current_date) AND (l.site_id IS NULL OR l.site_id = st.site_id));
\echo '-- Q20f laudos liberados por medico x unidade do exame (liberacao fora do vinculo = achado)'
SELECT v.signed_by, coalesce(s.name, '(sem unidade)') AS unidade_exame, count(*) FROM report.report_versions v
JOIN report.reports r ON r.id = v.report_id JOIN clinical.studies st ON st.id = r.study_id
LEFT JOIN tenancy.sites s ON s.id = st.site_id GROUP BY 1, 2 ORDER BY 1, 2;
\echo '-- Q20g RLS ativa e forcada nas tabelas de negocio (esperado: nenhuma linha)'
SELECT n.nspname || '.' || c.relname AS tabela, c.relrowsecurity, c.relforcerowsecurity
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r' AND n.nspname IN ('tenancy','auth','clinical','platform','audit','pacs','ris','report')
  AND EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attname = 'tenant_id' AND NOT a.attisdropped)
  AND NOT (c.relrowsecurity AND c.relforcerowsecurity) ORDER BY 1;

\echo '== Q30 auditoria da missao (acoes por ator e tipo, a partir de 2026-11-05)'
SELECT actor, action, target_type, count(*), min(at) AS primeira, max(at) AS ultima FROM audit.audit_log
WHERE at >= '2026-11-05' GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;
\echo '-- Q30b encadeamento: hash anterior de cada registro igual ao hash do anterior da mesma organizacao (esperado: 0)'
SELECT count(*) AS quebras FROM (
  SELECT seq, prev_hash, lag(hash) OVER (PARTITION BY tenant_id ORDER BY seq) AS anterior FROM audit.audit_log) x
WHERE anterior IS NOT NULL AND prev_hash <> anterior;
