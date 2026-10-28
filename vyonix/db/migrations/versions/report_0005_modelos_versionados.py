"""REPORT / TELELAUDO T3: versões dos modelos de laudo (rascunho → publicado → arquivado) com seções estruturadas
(técnica, achados, conclusão) e campos dinâmicos validados; associação do modelo a procedimento e unidade; o laudo
registra o modelo e a versão usados.

Revisão: report_0005
Anterior: report_0004
"""
from alembic import op
import sqlalchemy as sa


revision = 'report_0005'
down_revision = 'report_0004'
branch_labels = None
depends_on = None

TENANT_TABLES = ("report.template_versions",)
TENANT_EXPR = "nullif(current_setting('vyonix.tenant_id', true), '')::uuid"


def upgrade(role_prefix: str = "vyonix") -> None:
    op.create_table(
        'template_versions',
        sa.Column('template_id', sa.Uuid(), nullable=False), sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(12), nullable=False), sa.Column('technique', sa.Text(), nullable=False),
        sa.Column('findings', sa.Text(), nullable=False), sa.Column('conclusion', sa.Text(), nullable=False),
        sa.Column('created_by', sa.String(120), nullable=False), sa.Column('published_by', sa.String(120), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False), sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['template_id'], ['report.templates.id'], name=op.f('fk_template_versions_template_id')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_template_versions')), schema='report')
    op.create_index(op.f('ix_template_versions_tenant_id'), 'template_versions', ['tenant_id'], schema='report')
    op.create_index('uq_report_template_versions', 'template_versions', ['tenant_id', 'template_id', 'version'],
                    unique=True, schema='report')
    op.add_column('templates', sa.Column('procedure_id', sa.Uuid(), nullable=True), schema='report')
    op.add_column('templates', sa.Column('site_id', sa.Uuid(), nullable=True), schema='report')
    op.add_column('templates', sa.Column('preferred', sa.Boolean(), nullable=False, server_default=sa.text('false')),
                  schema='report')
    op.create_foreign_key('fk_templates_procedure_id', 'templates', 'procedures', ['procedure_id'], ['id'],
                          source_schema='report', referent_schema='clinical')
    op.create_foreign_key('fk_templates_site_id', 'templates', 'sites', ['site_id'], ['id'],
                          source_schema='report', referent_schema='tenancy')
    op.add_column('reports', sa.Column('template_id', sa.Uuid(), nullable=True), schema='report')
    op.add_column('reports', sa.Column('template_version', sa.Integer(), nullable=True), schema='report')
    for t in TENANT_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) "
                   f"WITH CHECK (tenant_id = {TENANT_EXPR})")


def downgrade(role_prefix: str = "vyonix") -> None:
    op.drop_column('reports', 'template_version', schema='report')
    op.drop_column('reports', 'template_id', schema='report')
    op.drop_constraint('fk_templates_site_id', 'templates', schema='report')
    op.drop_constraint('fk_templates_procedure_id', 'templates', schema='report')
    for c in ('preferred', 'site_id', 'procedure_id'):
        op.drop_column('templates', c, schema='report')
    op.drop_table('template_versions', schema='report')
