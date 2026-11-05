"""MISSÃO 3 (rascunho A08): origem do estudo (unidade/gateway), equipamentos por gateway, recibos de ingestão por
instância e manifestos de reconciliação por estudo.

Aditiva. ``dicom_nodes.site_id`` (pacs_0006, sem FK) ganha FK composta ``NOT VALID``: vale para linhas novas e
alteradas; as antigas não são rejeitadas. Se não houver órfãs, a FK é validada aqui; havendo, fica NOT VALID e as
órfãs são listadas (correção manual, nunca apagadas).

Revisão: pacs_0011
Anterior: pacs_0010 (depende de core_0005)
"""
from alembic import op
import sqlalchemy as sa


revision = 'pacs_0011'
down_revision = 'pacs_0010'
branch_labels = None
depends_on = 'core_0005'

TENANT_EXPR = "nullif(current_setting('vyonix.tenant_id', true), '')::uuid"
ORPHAN_SQL = ("SELECT n.id FROM pacs.dicom_nodes n WHERE n.site_id IS NOT NULL AND NOT EXISTS "
              "(SELECT 1 FROM tenancy.sites s WHERE s.tenant_id = n.tenant_id AND s.id = n.site_id)")


def _fk(table, name, cols, ref, refcols, not_valid=False):
    op.execute(f"ALTER TABLE pacs.{table} ADD CONSTRAINT {name} FOREIGN KEY ({', '.join(cols)}) "
               f"REFERENCES {ref} ({', '.join(refcols)})" + (" NOT VALID" if not_valid else ""))


def _rls(t):
    op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) "
               f"WITH CHECK (tenant_id = {TENANT_EXPR})")


def upgrade(role_prefix: str = "vyonix") -> None:
    p = role_prefix
    bind = op.get_bind()
    # --- equipamentos: reaproveita pacs.dicom_nodes ------------------------------------------------------------
    op.add_column('dicom_nodes', sa.Column('gateway_id', sa.Uuid(), nullable=True), schema='pacs')
    _fk('dicom_nodes', 'fk_dicom_nodes_gateway', ['tenant_id', 'gateway_id'], 'tenancy.gateways', ['tenant_id', 'id'])
    _fk('dicom_nodes', 'fk_dicom_nodes_site', ['tenant_id', 'site_id'], 'tenancy.sites', ['tenant_id', 'id'],
        not_valid=True)
    orphans = [str(r[0]) for r in bind.execute(sa.text(ORPHAN_SQL))]
    if orphans:
        print(f"[pacs_0011] AVISO: {len(orphans)} nó(s) DICOM com unidade inexistente; FK fica NOT VALID: {orphans}")
    else:
        op.execute("ALTER TABLE pacs.dicom_nodes VALIDATE CONSTRAINT fk_dicom_nodes_site")
    op.create_index('ix_pacs_dicom_nodes_gateway', 'dicom_nodes', ['tenant_id', 'gateway_id'], schema='pacs',
                    postgresql_where=sa.text('gateway_id IS NOT NULL'))

    # --- origem do estudo e rota por unidade ---------------------------------------------------------------------
    op.add_column('studies', sa.Column('site_id', sa.Uuid(), nullable=True), schema='pacs')
    op.add_column('studies', sa.Column('gateway_id', sa.Uuid(), nullable=True), schema='pacs')
    _fk('studies', 'fk_pacs_studies_site', ['tenant_id', 'site_id'], 'tenancy.sites', ['tenant_id', 'id'])
    _fk('studies', 'fk_pacs_studies_gateway', ['tenant_id', 'gateway_id'], 'tenancy.gateways', ['tenant_id', 'id'])
    # produção: CREATE INDEX CONCURRENTLY fora da transação (tabela grande)
    op.create_index('ix_pacs_studies_site_date', 'studies', ['tenant_id', 'site_id', 'study_date'], schema='pacs',
                    postgresql_where=sa.text('site_id IS NOT NULL'))
    op.add_column('ae_routes', sa.Column('site_id', sa.Uuid(), nullable=True), schema='pacs')
    _fk('ae_routes', 'fk_ae_routes_site', ['tenant_id', 'site_id'], 'tenancy.sites', ['tenant_id', 'id'])

    # --- recibos de ingestão por instância (trilha; somente inserção) -----------------------------------------
    op.execute("""CREATE TABLE pacs.ingest_receipts (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        tenant_id uuid NOT NULL,
        gateway_id uuid NOT NULL,
        site_id uuid NOT NULL,
        request_id uuid NOT NULL,
        study_uid varchar(64) NOT NULL,
        series_uid varchar(64) NOT NULL,
        sop_uid varchar(64) NOT NULL,
        sha256 char(64) NOT NULL,
        size_bytes bigint NOT NULL,
        outcome varchar(10) NOT NULL,
        instance_id uuid,
        detail varchar(200),
        received_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ck_ingest_receipts_outcome CHECK (outcome IN ('stored','duplicate','conflict','rejected','integrity')),
        CONSTRAINT ck_ingest_receipts_sha CHECK (sha256 ~ '^[0-9a-f]{64}$'),
        CONSTRAINT fk_ingest_receipts_gateway FOREIGN KEY (tenant_id, gateway_id) REFERENCES tenancy.gateways (tenant_id, id),
        CONSTRAINT fk_ingest_receipts_site FOREIGN KEY (tenant_id, site_id) REFERENCES tenancy.sites (tenant_id, id))""")
    # idempotência: o mesmo conteúdo do mesmo gateway gera um único recibo (reenvio devolve o recibo existente)
    op.execute("CREATE UNIQUE INDEX uq_ingest_receipts_content ON pacs.ingest_receipts "
               "(tenant_id, gateway_id, sop_uid, sha256)")
    op.execute("CREATE UNIQUE INDEX uq_ingest_receipts_request ON pacs.ingest_receipts (tenant_id, gateway_id, request_id)")
    op.execute("CREATE INDEX ix_ingest_receipts_study ON pacs.ingest_receipts (tenant_id, study_uid)")
    op.execute("CREATE INDEX ix_ingest_receipts_gw_at ON pacs.ingest_receipts (tenant_id, gateway_id, received_at)")
    op.execute("""CREATE FUNCTION pacs.forbid_change() RETURNS trigger LANGUAGE plpgsql AS $$
                  BEGIN RAISE EXCEPTION '% é somente inserção', TG_TABLE_NAME; END $$""")
    op.execute("CREATE TRIGGER ingest_receipts_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON pacs.ingest_receipts "
               "FOR EACH STATEMENT EXECUTE FUNCTION pacs.forbid_change()")

    # --- manifesto por estudo (declarado pelo gateway; conferido pelo Worker) --------------------------------
    op.execute("""CREATE TABLE pacs.study_manifests (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        tenant_id uuid NOT NULL,
        gateway_id uuid NOT NULL,
        study_uid varchar(64) NOT NULL,
        manifest_sha256 char(64) NOT NULL,
        instance_count integer NOT NULL CHECK (instance_count >= 0),
        total_bytes bigint NOT NULL CHECK (total_bytes >= 0),
        declared_at timestamptz NOT NULL DEFAULT now(),
        status varchar(12) NOT NULL DEFAULT 'pending',
        central_count integer,
        missing_count integer,
        checked_at timestamptz,
        CONSTRAINT ck_study_manifests_status CHECK (status IN ('pending','complete','incomplete','mismatch')),
        CONSTRAINT fk_study_manifests_gateway FOREIGN KEY (tenant_id, gateway_id) REFERENCES tenancy.gateways (tenant_id, id))""")
    op.execute("CREATE UNIQUE INDEX uq_study_manifests ON pacs.study_manifests "
               "(tenant_id, gateway_id, study_uid, manifest_sha256)")
    op.execute("CREATE INDEX ix_study_manifests_open ON pacs.study_manifests (tenant_id, status, declared_at) "
               "WHERE status <> 'complete'")
    op.execute("CREATE TRIGGER study_manifests_no_delete BEFORE DELETE OR TRUNCATE ON pacs.study_manifests "
               "FOR EACH STATEMENT EXECUTE FUNCTION pacs.forbid_change()")

    for t in ("pacs.ingest_receipts", "pacs.study_manifests"):
        _rls(t)
        op.execute(f"REVOKE ALL ON {t} FROM {p}_app, {p}_service")
        op.execute(f"GRANT SELECT, INSERT ON {t} TO {p}_app, {p}_service")
    # o Worker atualiza só o resultado da conferência (privilégio por coluna)
    op.execute(f"GRANT UPDATE (status, central_count, missing_count, checked_at) ON pacs.study_manifests TO {p}_service")


def downgrade(role_prefix: str = "vyonix") -> None:
    bind = op.get_bind()
    for t in ("pacs.ingest_receipts", "pacs.study_manifests"):
        n = bind.execute(sa.text(f"SELECT count(*) FROM {t}")).scalar()
        if n:
            raise RuntimeError(f"Downgrade recusado: {t} tem {n} linha(s) (trilha de custódia).")
    for t, c in (("studies", "site_id"), ("studies", "gateway_id"), ("ae_routes", "site_id"),
                 ("dicom_nodes", "gateway_id")):
        if bind.execute(sa.text(f"SELECT count(*) FROM pacs.{t} WHERE {c} IS NOT NULL")).scalar():
            raise RuntimeError(f"Downgrade recusado: pacs.{t}.{c} já tem valores.")
    op.execute("DROP TABLE pacs.study_manifests")
    op.execute("DROP TABLE pacs.ingest_receipts")
    op.execute("DROP FUNCTION pacs.forbid_change()")
    op.drop_constraint('fk_ae_routes_site', 'ae_routes', schema='pacs', type_='foreignkey')
    op.drop_column('ae_routes', 'site_id', schema='pacs')
    op.drop_index('ix_pacs_studies_site_date', table_name='studies', schema='pacs')
    op.drop_constraint('fk_pacs_studies_gateway', 'studies', schema='pacs', type_='foreignkey')
    op.drop_constraint('fk_pacs_studies_site', 'studies', schema='pacs', type_='foreignkey')
    op.drop_column('studies', 'gateway_id', schema='pacs')
    op.drop_column('studies', 'site_id', schema='pacs')
    op.drop_index('ix_pacs_dicom_nodes_gateway', table_name='dicom_nodes', schema='pacs')
    op.drop_constraint('fk_dicom_nodes_site', 'dicom_nodes', schema='pacs', type_='foreignkey')   # site_id fica
    op.drop_constraint('fk_dicom_nodes_gateway', 'dicom_nodes', schema='pacs', type_='foreignkey')
    op.drop_column('dicom_nodes', 'gateway_id', schema='pacs')
