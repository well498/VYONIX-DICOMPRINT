"""REPORT / TELELAUDO T1: cadastro de médicos (CRM/UF, RQE, especialidades, identificação no rodapé) e vínculos com a
organização ou unidades, com vigência. Só médico com vínculo vigente libera laudo.

Revisão: report_0003
Anterior: report_0002
"""
from alembic import op
import sqlalchemy as sa


revision = 'report_0003'
down_revision = 'report_0002'
branch_labels = None
depends_on = None

TENANT_TABLES = ("report.physicians", "report.physician_links")
TENANT_EXPR = "nullif(current_setting('vyonix.tenant_id', true), '')::uuid"


def _common():
    return [sa.Column('id', sa.Uuid(), nullable=False), sa.Column('tenant_id', sa.Uuid(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('row_version', sa.Integer(), nullable=False)]


def upgrade(role_prefix: str = "vyonix") -> None:
    op.create_table(
        'physicians',
        sa.Column('user_id', sa.Uuid(), nullable=False), sa.Column('full_name', sa.String(160), nullable=False),
        sa.Column('crm', sa.String(10), nullable=False), sa.Column('crm_uf', sa.String(2), nullable=False),
        sa.Column('rqe', sa.String(40), nullable=True), sa.Column('specialties', sa.JSON(), nullable=False),
        sa.Column('footer', sa.String(200), nullable=True), sa.Column('active', sa.Boolean(), nullable=False),
        *_common(),
        sa.ForeignKeyConstraint(['user_id'], ['auth.users.id'], name=op.f('fk_physicians_user_id')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_physicians')), schema='report')
    op.create_index(op.f('ix_physicians_tenant_id'), 'physicians', ['tenant_id'], schema='report')
    op.create_index('uq_report_physicians_user', 'physicians', ['tenant_id', 'user_id'], unique=True, schema='report')
    op.create_index('uq_report_physicians_crm', 'physicians', ['tenant_id', 'crm', 'crm_uf'], unique=True,
                    schema='report')
    op.create_table(
        'physician_links',
        sa.Column('physician_id', sa.Uuid(), nullable=False), sa.Column('site_id', sa.Uuid(), nullable=True),
        sa.Column('valid_from', sa.Date(), nullable=False), sa.Column('valid_to', sa.Date(), nullable=True),
        sa.Column('created_by', sa.String(120), nullable=False), *_common(),
        sa.ForeignKeyConstraint(['physician_id'], ['report.physicians.id'], name=op.f('fk_physician_links_physician_id')),
        sa.ForeignKeyConstraint(['site_id'], ['tenancy.sites.id'], name=op.f('fk_physician_links_site_id')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_physician_links')), schema='report')
    op.create_index(op.f('ix_physician_links_tenant_id'), 'physician_links', ['tenant_id'], schema='report')
    op.create_index(op.f('ix_physician_links_physician_id'), 'physician_links', ['physician_id'], schema='report')
    for t in TENANT_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) "
                   f"WITH CHECK (tenant_id = {TENANT_EXPR})")


def downgrade(role_prefix: str = "vyonix") -> None:
    op.drop_table('physician_links', schema='report')
    op.drop_table('physicians', schema='report')
