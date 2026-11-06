"""CLINICAL: unidade do pedido e origem da unidade do estudo (P0 0.3.2 — isolamento por unidade).

Aditiva: só cria colunas NULL, índices e uma tabela somente-inserção. NENHUM dado existente é alterado: a atribuição
de unidade aos estudos antigos é feita depois, pela aplicação (``vyonix unidade-simular`` / ``unidade-aplicar``), com
simulação aprovada pelo proprietário e auditoria por estudo.

Revisão: clinical_0001
Depende de: core_0004
"""
from alembic import op
import sqlalchemy as sa

revision = 'clinical_0001'
down_revision = None
branch_labels = ('clinical',)
depends_on = 'core_0004'

TENANT_EXPR = "nullif(current_setting('vyonix.tenant_id', true), '')::uuid"
SOURCES = ('pedido', 'atendimento', 'agendamento', 'no_dicom', 'unica', 'manual', 'simulacao')


def upgrade(role_prefix: str = "vyonix") -> None:
    app, service = f'"{role_prefix}_app"', f'"{role_prefix}_service"'
    op.add_column('orders', sa.Column('site_id', sa.Uuid(), nullable=True), schema='clinical')
    op.create_foreign_key('fk_orders_site_id', 'orders', 'sites', ['site_id'], ['id'],
                          source_schema='clinical', referent_schema='tenancy')
    op.add_column('studies', sa.Column('site_source', sa.String(12), nullable=True), schema='clinical')
    op.add_column('studies', sa.Column('site_set_at', sa.DateTime(timezone=True), nullable=True), schema='clinical')
    op.add_column('studies', sa.Column('site_set_by', sa.String(120), nullable=True), schema='clinical')
    op.create_check_constraint('ck_studies_site_source', 'studies',
                               "site_source IS NULL OR site_source IN (%s)" % ",".join(f"'{x}'" for x in SOURCES),
                               schema='clinical')
    op.create_index('ix_clinical_studies_site_date', 'studies', ['tenant_id', 'site_id', 'study_date'], schema='clinical')
    op.create_index('ix_clinical_studies_sem_unidade', 'studies', ['tenant_id'], schema='clinical',
                    postgresql_where=sa.text('site_id IS NULL'))
    op.create_index('ix_clinical_studies_order', 'studies', ['order_id'], schema='clinical',
                    postgresql_where=sa.text('order_id IS NOT NULL'))
    op.create_index('ix_clinical_orders_site', 'orders', ['tenant_id', 'site_id'], schema='clinical')

    op.create_table(
        'study_site_assignments',
        sa.Column('study_id', sa.Uuid(), sa.ForeignKey('clinical.studies.id'), nullable=False),
        sa.Column('from_site_id', sa.Uuid(), nullable=True),
        sa.Column('to_site_id', sa.Uuid(), sa.ForeignKey('tenancy.sites.id'), nullable=False),
        sa.Column('source', sa.String(12), nullable=False),
        sa.Column('evidence', sa.JSON(), nullable=False),
        sa.Column('simulation_sha256', sa.String(64), nullable=True),
        sa.Column('approved_by', sa.String(120), nullable=True),
        sa.Column('actor', sa.String(120), nullable=False),
        sa.Column('actor_id', sa.Uuid(), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_study_site_assignments')),
        schema='clinical')
    op.create_index('ix_clinical_ssa_tenant_id', 'study_site_assignments', ['tenant_id'], schema='clinical')
    op.create_index('ix_clinical_ssa_study', 'study_site_assignments', ['tenant_id', 'study_id', 'created_at'],
                    schema='clinical')
    op.create_index('uq_clinical_ssa_sim_study', 'study_site_assignments',
                    ['tenant_id', 'simulation_sha256', 'study_id'], unique=True, schema='clinical',
                    postgresql_where=sa.text('simulation_sha256 IS NOT NULL'))
    t = 'clinical.study_site_assignments'
    op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) "
               f"WITH CHECK (tenant_id = {TENANT_EXPR})")
    op.execute(f"REVOKE ALL ON {t} FROM {app}, {service}")
    op.execute(f"GRANT SELECT, INSERT ON {t} TO {app}, {service}")


def downgrade(role_prefix: str = "vyonix") -> None:          # só testes; nunca em produção
    op.drop_table('study_site_assignments', schema='clinical')
    op.drop_index('ix_clinical_orders_site', table_name='orders', schema='clinical')
    op.drop_index('ix_clinical_studies_order', table_name='studies', schema='clinical')
    op.drop_index('ix_clinical_studies_sem_unidade', table_name='studies', schema='clinical')
    op.drop_index('ix_clinical_studies_site_date', table_name='studies', schema='clinical')
    op.drop_constraint('ck_studies_site_source', 'studies', schema='clinical')
    for c in ('site_set_by', 'site_set_at', 'site_source'):
        op.drop_column('studies', c, schema='clinical')
    op.drop_constraint('fk_orders_site_id', 'orders', schema='clinical')
    op.drop_column('orders', 'site_id', schema='clinical')
