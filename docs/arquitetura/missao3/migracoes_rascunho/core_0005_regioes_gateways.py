"""MISSÃO 3 (rascunho A08): região opcional, gateways DICOM locais (sem HWID), credenciais mTLS e heartbeats.

Aditiva: nenhuma coluna/tabela existente é removida ou alterada em conteúdo. ``tenancy.installations`` (legado, HWID)
fica intacta e não é reaproveitada. ``sites`` ganha ``region_id`` (nulo = sem região) e um índice único
(tenant_id, id) para chaves estrangeiras compostas (impede referência entre instituições — B-05).

Revisão: core_0005
Anterior: core_0004
"""
from alembic import op
import sqlalchemy as sa


revision = 'core_0005'
down_revision = 'core_0004'
branch_labels = None
depends_on = None

TENANT_EXPR = "nullif(current_setting('vyonix.tenant_id', true), '')::uuid"
HB_MONTHS = 3          # partições mensais criadas à frente (mais a DEFAULT, que nunca recusa um heartbeat)


def _base():
    return [sa.Column('id', sa.Uuid(), nullable=False),
            sa.Column('tenant_id', sa.Uuid(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('row_version', sa.Integer(), nullable=False, server_default='1')]


def _rls(t):
    op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) "
               f"WITH CHECK (tenant_id = {TENANT_EXPR})")


def _grant(t, prefix, app=None, service=None):
    a, s = f"{prefix}_app", f"{prefix}_service"
    op.execute(f"REVOKE ALL ON {t} FROM {a}, {s}")       # remove os privilégios padrão herdados do esquema
    if app:
        op.execute(f"GRANT {app} ON {t} TO {a}")
    if service:
        op.execute(f"GRANT {service} ON {t} TO {s}")


def upgrade(role_prefix: str = "vyonix") -> None:
    p = role_prefix
    # --- chave composta para FKs sem cruzar instituição ---------------------------------------------------------
    op.create_index('uq_sites_tenant_id_id', 'sites', ['tenant_id', 'id'], unique=True, schema='tenancy')

    # --- regiões (opcional) ------------------------------------------------------------------------------------------
    op.create_table(
        'regions',
        sa.Column('code', sa.String(40), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        *_base(),
        sa.PrimaryKeyConstraint('id', name='pk_regions'),
        sa.UniqueConstraint('tenant_id', 'id', name='uq_regions_tenant_id_id'),
        sa.CheckConstraint("code ~ '^[a-z0-9][a-z0-9_-]{0,39}$'", name='ck_regions_code'),
        schema='tenancy')
    op.create_index('uq_regions_tenant_code', 'regions', ['tenant_id', 'code'], unique=True, schema='tenancy')
    op.add_column('sites', sa.Column('region_id', sa.Uuid(), nullable=True), schema='tenancy')
    op.create_foreign_key('fk_sites_region', 'sites', 'regions', ['tenant_id', 'region_id'], ['tenant_id', 'id'],
                          source_schema='tenancy', referent_schema='tenancy')
    op.create_index('ix_sites_region', 'sites', ['tenant_id', 'region_id'], schema='tenancy',
                    postgresql_where=sa.text('region_id IS NOT NULL'))

    # --- gateways (sem HWID; identidade = certificado de cliente) ------------------------------------------------
    op.create_table(
        'gateways',
        sa.Column('site_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('profile', sa.String(16), nullable=False, server_default='essential'),
        sa.Column('status', sa.String(12), nullable=False, server_default='pending'),
        sa.Column('enroll_code_hash', sa.String(64), nullable=True),     # código único de adesão (SHA-256)
        sa.Column('enroll_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('enrolled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.String(40), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_sync_ok_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('queue_pending', sa.Integer(), nullable=True),
        sa.Column('queue_failed', sa.Integer(), nullable=True),
        sa.Column('oldest_pending_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.String(120), nullable=False),
        sa.Column('status_reason', sa.String(300), nullable=True),
        *_base(),
        sa.PrimaryKeyConstraint('id', name='pk_gateways'),
        sa.UniqueConstraint('tenant_id', 'id', name='uq_gateways_tenant_id_id'),
        sa.ForeignKeyConstraint(['tenant_id', 'site_id'], ['tenancy.sites.tenant_id', 'tenancy.sites.id'],
                                name='fk_gateways_site'),
        sa.CheckConstraint("profile IN ('essential','professional','hospital','enterprise')",
                           name='ck_gateways_profile'),
        sa.CheckConstraint("status IN ('pending','active','suspended','revoked')", name='ck_gateways_status'),
        schema='tenancy')
    op.create_index('uq_gateways_site_name', 'gateways', ['tenant_id', 'site_id', 'name'], unique=True,
                    schema='tenancy')
    op.create_index('ix_gateways_status_seen', 'gateways', ['tenant_id', 'status', 'last_seen_at'],
                    schema='tenancy')

    op.create_table(
        'gateway_credentials',
        sa.Column('gateway_id', sa.Uuid(), nullable=False),
        sa.Column('fingerprint_sha256', sa.String(64), nullable=False),
        sa.Column('serial', sa.String(64), nullable=False),
        sa.Column('not_before', sa.DateTime(timezone=True), nullable=False),
        sa.Column('not_after', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_reason', sa.String(200), nullable=True),
        *_base(),
        sa.PrimaryKeyConstraint('id', name='pk_gateway_credentials'),
        sa.ForeignKeyConstraint(['tenant_id', 'gateway_id'], ['tenancy.gateways.tenant_id', 'tenancy.gateways.id'],
                                name='fk_gateway_credentials_gateway'),
        sa.CheckConstraint("fingerprint_sha256 ~ '^[0-9a-f]{64}$'", name='ck_gateway_credentials_fp'),
        sa.CheckConstraint('not_after > not_before', name='ck_gateway_credentials_validity'),
        schema='tenancy')
    # único no servidor inteiro: o certificado identifica o gateway antes de haver instituição na sessão
    op.create_index('uq_gateway_credentials_fp', 'gateway_credentials', ['fingerprint_sha256'], unique=True,
                    schema='tenancy')
    op.create_index('ix_gateway_credentials_gw', 'gateway_credentials', ['tenant_id', 'gateway_id'],
                    schema='tenancy')
    # revogação é definitiva (não volta a nulo) e o certificado não muda depois de emitido
    op.execute("""CREATE FUNCTION tenancy.credential_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
            RAISE EXCEPTION 'revogação de credencial é definitiva'; END IF;
          IF NEW.fingerprint_sha256 <> OLD.fingerprint_sha256 OR NEW.gateway_id <> OLD.gateway_id
             OR NEW.tenant_id <> OLD.tenant_id OR NEW.not_after <> OLD.not_after THEN
            RAISE EXCEPTION 'credencial emitida não pode ser alterada'; END IF;
          RETURN NEW; END $$""")
    op.execute("CREATE TRIGGER gateway_credentials_guard BEFORE UPDATE ON tenancy.gateway_credentials "
               "FOR EACH ROW EXECUTE FUNCTION tenancy.credential_guard()")

    # --- heartbeats: série temporal enxuta, particionada por mês, sem PHI ----------------------------------------
    op.execute("""CREATE TABLE tenancy.gateway_heartbeats (
        tenant_id uuid NOT NULL,
        gateway_id uuid NOT NULL,
        at timestamptz NOT NULL DEFAULT now(),
        version varchar(40),
        queue_pending integer, queue_failed integer, oldest_pending_at timestamptz,
        disk_free_pct numeric(5,2), last_sync_ok_at timestamptz,
        flags smallint NOT NULL DEFAULT 0,
        CONSTRAINT pk_gateway_heartbeats PRIMARY KEY (tenant_id, gateway_id, at),
        CONSTRAINT fk_gateway_heartbeats_gateway FOREIGN KEY (tenant_id, gateway_id)
            REFERENCES tenancy.gateways (tenant_id, id)
    ) PARTITION BY RANGE (at)""")
    op.execute("CREATE TABLE tenancy.gateway_heartbeats_default PARTITION OF tenancy.gateway_heartbeats DEFAULT")
    op.execute("""CREATE FUNCTION tenancy.ensure_heartbeat_partition(p_month date) RETURNS text
        LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, tenancy AS $$
        DECLARE m date := date_trunc('month', p_month)::date; n text := 'gateway_heartbeats_' || to_char(m, 'YYYYMM'); g text;
        BEGIN
          IF to_regclass('tenancy.' || n) IS NULL THEN
            EXECUTE format('CREATE TABLE tenancy.%I PARTITION OF tenancy.gateway_heartbeats FOR VALUES FROM (%L) TO (%L)',
                           n, m, (m + interval '1 month')::date);
          END IF;
          -- partições não herdam o RLS do pai: tira os privilégios padrão herdados do esquema (acesso só pelo pai)
          SELECT string_agg(DISTINCT quote_ident(grantee), ', ') INTO g FROM information_schema.role_table_grants
           WHERE table_schema = 'tenancy' AND table_name = n AND grantee <> current_user;
          IF g IS NOT NULL THEN EXECUTE format('REVOKE ALL ON tenancy.%I FROM %s', n, g); END IF;
          RETURN n; END $$""")
    op.execute("REVOKE ALL ON FUNCTION tenancy.ensure_heartbeat_partition(date) FROM PUBLIC")
    for i in range(HB_MONTHS):
        op.execute(f"SELECT tenancy.ensure_heartbeat_partition((date_trunc('month', now()) + interval '{i} month')::date)")

    # --- RLS e privilégios ---------------------------------------------------------------------------------------
    for t in ("tenancy.regions", "tenancy.gateways", "tenancy.gateway_credentials", "tenancy.gateway_heartbeats"):
        _rls(t)
    _grant("tenancy.regions", p, app="SELECT, INSERT, UPDATE", service="SELECT")
    _grant("tenancy.gateways", p, app="SELECT, INSERT, UPDATE", service="SELECT, UPDATE")
    _grant("tenancy.gateway_credentials", p, app="SELECT, INSERT, UPDATE", service="SELECT")
    _grant("tenancy.gateway_heartbeats", p, app="SELECT, INSERT", service="SELECT, INSERT")
    _revoke_partitions(p)

    # resolução do gateway pelo certificado (antes de haver instituição na sessão), como resolve_organization
    op.execute(f"""CREATE FUNCTION tenancy.resolve_gateway(p_fingerprint text)
        RETURNS TABLE(gateway_id uuid, tenant_id uuid, site_id uuid, profile varchar)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, tenancy AS $$
        SELECT g.id, g.tenant_id, g.site_id, g.profile
          FROM tenancy.gateway_credentials c
          JOIN tenancy.gateways g ON g.tenant_id = c.tenant_id AND g.id = c.gateway_id
          JOIN tenancy.organizations o ON o.id = g.tenant_id
          JOIN tenancy.sites s ON s.tenant_id = g.tenant_id AND s.id = g.site_id
         WHERE c.fingerprint_sha256 = lower(p_fingerprint) AND c.revoked_at IS NULL
           AND now() >= c.not_before AND now() < c.not_after
           AND g.status = 'active' AND o.active AND s.active $$""")
    op.execute("REVOKE ALL ON FUNCTION tenancy.resolve_gateway(text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION tenancy.resolve_gateway(text) TO {p}_app, {p}_service")


def _revoke_partitions(p):
    """Partições não herdam as políticas do pai: acesso só pela tabela-mãe (onde está o RLS)."""
    bind = op.get_bind()
    for (n,) in bind.execute(sa.text("SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
                                     "WHERE i.inhparent = 'tenancy.gateway_heartbeats'::regclass")):
        op.execute(f'REVOKE ALL ON tenancy."{n}" FROM {p}_app, {p}_service')


def downgrade(role_prefix: str = "vyonix") -> None:
    bind = op.get_bind()
    for t in ("tenancy.regions", "tenancy.gateways", "tenancy.gateway_credentials"):
        n = bind.execute(sa.text(f"SELECT count(*) FROM {t}")).scalar()
        if n:
            raise RuntimeError(f"Downgrade recusado: {t} tem {n} linha(s); exporte antes (sem perda de dados).")
    if bind.execute(sa.text("SELECT count(*) FROM tenancy.sites WHERE region_id IS NOT NULL")).scalar():
        raise RuntimeError("Downgrade recusado: há unidades vinculadas a regiões.")
    op.execute("DROP FUNCTION IF EXISTS tenancy.resolve_gateway(text)")
    op.execute("DROP TABLE tenancy.gateway_heartbeats")           # série de monitoramento (descartável)
    op.execute("DROP FUNCTION IF EXISTS tenancy.ensure_heartbeat_partition(date)")
    op.drop_table('gateway_credentials', schema='tenancy')
    op.execute("DROP FUNCTION IF EXISTS tenancy.credential_guard()")
    op.drop_table('gateways', schema='tenancy')
    op.drop_index('ix_sites_region', table_name='sites', schema='tenancy')
    op.drop_constraint('fk_sites_region', 'sites', schema='tenancy', type_='foreignkey')
    op.drop_column('sites', 'region_id', schema='tenancy')
    op.drop_table('regions', schema='tenancy')
    op.drop_index('uq_sites_tenant_id_id', table_name='sites', schema='tenancy')
