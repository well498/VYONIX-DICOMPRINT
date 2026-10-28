"""REPORT / TELELAUDO T5: imagem da assinatura manuscrita do médico (elemento só visual), cifrada em repouso,
enviada pelo próprio médico, aplicada apenas com a autorização dele (revogável) e registrada na versão liberada.

Revisão: report_0006
Anterior: report_0005
"""
from alembic import op
import sqlalchemy as sa


revision = 'report_0006'
down_revision = 'report_0005'
branch_labels = None
depends_on = None

TENANT_TABLES = ("report.signature_images",)
TENANT_EXPR = "nullif(current_setting('vyonix.tenant_id', true), '')::uuid"


def upgrade(role_prefix: str = "vyonix") -> None:
    op.create_table(
        'signature_images',
        sa.Column('physician_id', sa.Uuid(), nullable=False), sa.Column('ciphertext', sa.LargeBinary(), nullable=False),
        sa.Column('nonce', sa.LargeBinary(), nullable=False), sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('width', sa.Integer(), nullable=False), sa.Column('height', sa.Integer(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False), sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['physician_id'], ['report.physicians.id'], name=op.f('fk_signature_images_physician')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_signature_images')), schema='report')
    op.create_index(op.f('ix_signature_images_tenant_id'), 'signature_images', ['tenant_id'], schema='report')
    op.add_column('physicians', sa.Column('use_signature_image', sa.Boolean(), nullable=False,
                                          server_default=sa.text('false')), schema='report')
    op.add_column('report_versions', sa.Column('signature_image_id', sa.Uuid(), nullable=True), schema='report')
    for t in TENANT_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) "
                   f"WITH CHECK (tenant_id = {TENANT_EXPR})")
    app, service = f"{role_prefix}_app", f"{role_prefix}_service"
    op.execute(f"REVOKE DELETE ON report.signature_images FROM {app}, {service}")


def downgrade(role_prefix: str = "vyonix") -> None:
    op.drop_column('report_versions', 'signature_image_id', schema='report')
    op.drop_column('physicians', 'use_signature_image', schema='report')
    op.drop_table('signature_images', schema='report')
