"""REPORT inicial: laudos, versões liberadas (imutáveis) e modelos.

Revisão: report_0001
Anterior: — (ramo próprio, depende do core_0001)
"""
from alembic import op
import sqlalchemy as sa


revision = 'report_0001'
down_revision = None
branch_labels = ('report',)
depends_on = 'core_0001'

TENANT_TABLES = ("report.templates", "report.reports", "report.report_versions")
TENANT_EXPR = "nullif(current_setting('vyonix.tenant_id', true), '')::uuid"


def _common():
    return [sa.Column('id', sa.Uuid(), nullable=False),
            sa.Column('tenant_id', sa.Uuid(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('row_version', sa.Integer(), nullable=False)]


def upgrade(role_prefix: str = "vyonix") -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS report")
    op.create_table(
        'templates',
        sa.Column('name', sa.String(120), nullable=False), sa.Column('modality', sa.String(16), nullable=True),
        sa.Column('body', sa.Text(), nullable=False), sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_by', sa.String(120), nullable=False), *_common(),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_templates')), schema='report')
    op.create_index(op.f('ix_templates_tenant_id'), 'templates', ['tenant_id'], schema='report')
    op.create_index('uq_report_templates_name', 'templates', ['tenant_id', 'name'], unique=True, schema='report')
    op.create_table(
        'reports',
        sa.Column('study_id', sa.Uuid(), nullable=False), sa.Column('order_id', sa.Uuid(), nullable=True),
        sa.Column('status', sa.String(10), nullable=False), sa.Column('body', sa.Text(), nullable=False),
        sa.Column('critical', sa.Boolean(), nullable=False), sa.Column('critical_note', sa.String(300), nullable=True),
        sa.Column('author', sa.String(120), nullable=False), sa.Column('finalized_by', sa.String(120), nullable=True),
        sa.Column('finalized_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False), *_common(),
        sa.ForeignKeyConstraint(['study_id'], ['clinical.studies.id'], name=op.f('fk_reports_study_id')),
        sa.ForeignKeyConstraint(['order_id'], ['clinical.orders.id'], name=op.f('fk_reports_order_id')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_reports')), schema='report')
    op.create_index(op.f('ix_reports_tenant_id'), 'reports', ['tenant_id'], schema='report')
    op.create_index('uq_report_reports_study', 'reports', ['tenant_id', 'study_id'], unique=True, schema='report')
    op.create_table(
        'report_versions',
        sa.Column('report_id', sa.Uuid(), nullable=False), sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(10), nullable=False), sa.Column('body', sa.Text(), nullable=False),
        sa.Column('critical', sa.Boolean(), nullable=False), sa.Column('signed_by', sa.String(120), nullable=False),
        sa.Column('signed_by_id', sa.Uuid(), nullable=True),
        sa.Column('signed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False), *_common(),
        sa.ForeignKeyConstraint(['report_id'], ['report.reports.id'], name=op.f('fk_report_versions_report_id')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_report_versions')), schema='report')
    op.create_index(op.f('ix_report_versions_tenant_id'), 'report_versions', ['tenant_id'], schema='report')
    op.create_index(op.f('ix_report_versions_report_id'), 'report_versions', ['report_id'], schema='report')
    op.create_index('uq_report_versions', 'report_versions', ['tenant_id', 'report_id', 'version'], unique=True,
                    schema='report')
    app, service = f"{role_prefix}_app", f"{role_prefix}_service"
    for t in TENANT_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) "
                   f"WITH CHECK (tenant_id = {TENANT_EXPR})")
    op.execute(f"GRANT USAGE ON SCHEMA report TO {app}, {service}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA report TO {app}, {service}")
    # versões liberadas são imutáveis também para a aplicação (só inserção e leitura)
    op.execute(f"REVOKE UPDATE, DELETE ON report.report_versions FROM {app}, {service}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA report GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES "
               f"TO {app}, {service}")


def downgrade(role_prefix: str = "vyonix") -> None:
    op.drop_table('report_versions', schema='report')
    op.drop_table('reports', schema='report')
    op.drop_table('templates', schema='report')
    op.execute("DROP SCHEMA IF EXISTS report")
