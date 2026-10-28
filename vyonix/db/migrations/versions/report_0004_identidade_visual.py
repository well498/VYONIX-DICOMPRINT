"""REPORT / TELELAUDO T2: identidade visual por organização e por unidade (versões imutáveis) e arquivos de imagem
(logomarca e papel timbrado) guardados no banco com SHA-256. O laudo registra as versões usadas na liberação.

Revisão: report_0004
Anterior: report_0003
"""
from alembic import op
import sqlalchemy as sa


revision = 'report_0004'
down_revision = 'report_0003'
branch_labels = None
depends_on = None

TENANT_TABLES = ("report.assets", "report.branding_versions")
TENANT_EXPR = "nullif(current_setting('vyonix.tenant_id', true), '')::uuid"


def _common():
    return [sa.Column('id', sa.Uuid(), nullable=False), sa.Column('tenant_id', sa.Uuid(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('row_version', sa.Integer(), nullable=False)]


def upgrade(role_prefix: str = "vyonix") -> None:
    op.create_table(
        'assets',
        sa.Column('kind', sa.String(20), nullable=False), sa.Column('media_type', sa.String(40), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False), sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('width', sa.Integer(), nullable=False), sa.Column('height', sa.Integer(), nullable=False),
        sa.Column('data', sa.LargeBinary(), nullable=False), sa.Column('created_by', sa.String(120), nullable=False),
        *_common(), sa.PrimaryKeyConstraint('id', name=op.f('pk_assets')), schema='report')
    op.create_index(op.f('ix_assets_tenant_id'), 'assets', ['tenant_id'], schema='report')
    op.create_table(
        'branding_versions',
        sa.Column('site_id', sa.Uuid(), nullable=True), sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('settings', sa.JSON(), nullable=False),
        sa.Column('logo_asset_id', sa.Uuid(), nullable=True), sa.Column('letterhead_asset_id', sa.Uuid(), nullable=True),
        sa.Column('created_by', sa.String(120), nullable=False), *_common(),
        sa.ForeignKeyConstraint(['site_id'], ['tenancy.sites.id'], name=op.f('fk_branding_versions_site_id')),
        sa.ForeignKeyConstraint(['logo_asset_id'], ['report.assets.id'], name=op.f('fk_branding_versions_logo')),
        sa.ForeignKeyConstraint(['letterhead_asset_id'], ['report.assets.id'],
                                name=op.f('fk_branding_versions_letterhead')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_branding_versions')), schema='report')
    op.create_index(op.f('ix_branding_versions_tenant_id'), 'branding_versions', ['tenant_id'], schema='report')
    op.create_index('uq_report_branding_version', 'branding_versions',
                    ['tenant_id', sa.text("coalesce(site_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
                     'version'], unique=True, schema='report')
    op.add_column('reports', sa.Column('branding_org_version', sa.Integer(), nullable=True), schema='report')
    op.add_column('reports', sa.Column('branding_site_version', sa.Integer(), nullable=True), schema='report')
    app, service = f"{role_prefix}_app", f"{role_prefix}_service"
    for t in TENANT_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) "
                   f"WITH CHECK (tenant_id = {TENANT_EXPR})")
    # versões de identidade e arquivos são imutáveis para a aplicação (só inserção e leitura)
    op.execute(f"REVOKE UPDATE, DELETE ON report.branding_versions, report.assets FROM {app}, {service}")


def downgrade(role_prefix: str = "vyonix") -> None:
    op.drop_column('reports', 'branding_site_version', schema='report')
    op.drop_column('reports', 'branding_org_version', schema='report')
    op.drop_table('branding_versions', schema='report')
    op.drop_table('assets', schema='report')
