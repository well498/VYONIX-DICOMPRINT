"""PACS: credenciais de curta duração para visualizadores externos (Weasis). Aditiva.

Revisão: pacs_0010
Anterior: pacs_0009
"""
from alembic import op
import sqlalchemy as sa


revision = 'pacs_0010'
down_revision = 'pacs_0009'
branch_labels = None
depends_on = None

TENANT_TABLES = ("pacs.viewer_tokens",)
TENANT_EXPR = "nullif(current_setting('vyonix.tenant_id', true), '')::uuid"


def upgrade(role_prefix: str = "vyonix") -> None:
    op.create_table(
        'viewer_tokens',
        sa.Column('token_hash', sa.String(64), nullable=False),
        sa.Column('kind', sa.String(10), nullable=False),
        sa.Column('viewer', sa.String(12), nullable=False),
        sa.Column('study_uid', sa.String(64), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_viewer_tokens')),
        schema='pacs')
    op.create_index(op.f('ix_viewer_tokens_tenant_id'), 'viewer_tokens', ['tenant_id'], schema='pacs')
    op.create_index('uq_pacs_viewer_tokens_hash', 'viewer_tokens', ['tenant_id', 'token_hash'], unique=True,
                    schema='pacs')
    app, service = f"{role_prefix}_app", f"{role_prefix}_service"
    for t in TENANT_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) "
                   f"WITH CHECK (tenant_id = {TENANT_EXPR})")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO {app}, {service}")


def downgrade(role_prefix: str = "vyonix") -> None:
    op.drop_table('viewer_tokens', schema='pacs')
