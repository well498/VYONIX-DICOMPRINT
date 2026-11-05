"""MISSÃO 3 (rascunho A08): escopo por região em user_roles (opcional) e selo HMAC da cadeia de auditoria (B-07).

* ``auth.user_roles.region_id``: papel válido em todas as unidades da região. Unidade e região são exclusivas
  (CHECK). O índice único passa a incluir a região (expand: cria o novo antes de remover o antigo; o novo é mais
  permissivo só para linhas com região, então nenhuma linha existente o viola).
* ``audit.audit_log.hmac``/``hmac_key_id``: HMAC-SHA256(chave fora do banco, hash) — nulo nas linhas antigas
  (a cadeia SHA-256 delas continua verificável). A tabela segue somente inserção.
* ``audit.audit_anchors``: âncoras periódicas (último seq/hash por instituição + HMAC + referência externa
  ao objeto gravado em S3 Object Lock). Somente inserção.

Revisão: core_0006
Anterior: core_0005
"""
from alembic import op
import sqlalchemy as sa


revision = 'core_0006'
down_revision = 'core_0005'
branch_labels = None
depends_on = None

TENANT_EXPR = "nullif(current_setting('vyonix.tenant_id', true), '')::uuid"


def upgrade(role_prefix: str = "vyonix") -> None:
    p = role_prefix
    op.add_column('user_roles', sa.Column('region_id', sa.Uuid(), nullable=True), schema='auth')
    op.create_foreign_key('fk_user_roles_region', 'user_roles', 'regions', ['tenant_id', 'region_id'],
                          ['tenant_id', 'id'], source_schema='auth', referent_schema='tenancy')
    op.create_check_constraint('ck_user_roles_one_scope', 'user_roles', 'site_id IS NULL OR region_id IS NULL',
                               schema='auth')
    op.create_index('uq_user_roles_user_role_scope', 'user_roles', ['user_id', 'role_id', 'site_id', 'region_id'],
                    unique=True, schema='auth', postgresql_nulls_not_distinct=True)
    op.drop_index('uq_user_roles_user_role_site', table_name='user_roles', schema='auth')

    # auditoria: selo com chave (a chave fica no cofre/KMS, nunca no banco)
    op.add_column('audit_log', sa.Column('hmac', sa.String(64), nullable=True), schema='audit')
    op.add_column('audit_log', sa.Column('hmac_key_id', sa.String(40), nullable=True), schema='audit')
    op.execute("""CREATE TABLE audit.audit_anchors (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        tenant_id uuid NOT NULL,
        at timestamptz NOT NULL DEFAULT now(),
        last_seq bigint NOT NULL,
        last_hash varchar(64) NOT NULL,
        entries bigint NOT NULL,
        hmac varchar(64) NOT NULL,
        hmac_key_id varchar(40) NOT NULL,
        external_ref varchar(300),
        CONSTRAINT ck_audit_anchors_hash CHECK (last_hash ~ '^[0-9a-f]{64}$'))""")
    op.execute("CREATE UNIQUE INDEX uq_audit_anchors_tenant_seq ON audit.audit_anchors (tenant_id, last_seq)")
    op.execute("ALTER TABLE audit.audit_anchors ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit.audit_anchors FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON audit.audit_anchors USING (tenant_id = {TENANT_EXPR}) "
               f"WITH CHECK (tenant_id = {TENANT_EXPR})")
    op.execute(f"REVOKE ALL ON audit.audit_anchors FROM {p}_app, {p}_service")
    op.execute(f"GRANT SELECT ON audit.audit_anchors TO {p}_app")
    op.execute(f"GRANT SELECT, INSERT ON audit.audit_anchors TO {p}_service")
    op.execute("CREATE TRIGGER audit_anchors_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON audit.audit_anchors "
               "FOR EACH STATEMENT EXECUTE FUNCTION audit.forbid_change()")


def downgrade(role_prefix: str = "vyonix") -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT count(*) FROM auth.user_roles WHERE region_id IS NOT NULL")).scalar():
        raise RuntimeError("Downgrade recusado: há papéis com escopo de região (seriam perdidos).")
    if bind.execute(sa.text("SELECT count(*) FROM audit.audit_anchors")).scalar() or \
       bind.execute(sa.text("SELECT count(*) FROM audit.audit_log WHERE hmac IS NOT NULL")).scalar():
        raise RuntimeError("Downgrade recusado: a auditoria já tem selos/âncoras (trilha não é descartada).")
    op.execute("DROP TABLE audit.audit_anchors")
    op.drop_column('audit_log', 'hmac_key_id', schema='audit')
    op.drop_column('audit_log', 'hmac', schema='audit')
    op.create_index('uq_user_roles_user_role_site', 'user_roles', ['user_id', 'role_id', 'site_id'], unique=True,
                    schema='auth', postgresql_nulls_not_distinct=True)
    op.drop_index('uq_user_roles_user_role_scope', table_name='user_roles', schema='auth')
    op.drop_constraint('ck_user_roles_one_scope', 'user_roles', schema='auth', type_='check')
    op.drop_constraint('fk_user_roles_region', 'user_roles', schema='auth', type_='foreignkey')
    op.drop_column('user_roles', 'region_id', schema='auth')
