"""PACS: fila de sincronização edge → central (protótipo da ADR-0014; nenhuma tarefa usa esta tabela por padrão).

Revisão: pacs_0008
Anterior: pacs_0007
"""
from alembic import op
import sqlalchemy as sa


revision = 'pacs_0008'
down_revision = 'pacs_0007'
branch_labels = None
depends_on = None

TENANT_TABLES = ("pacs.edge_sync",)
TENANT_EXPR = "nullif(current_setting('vyonix.tenant_id', true), '')::uuid"


def upgrade(role_prefix: str = "vyonix") -> None:
    op.create_table(
        'edge_sync',
        sa.Column('instance_id', sa.Uuid(), nullable=False),
        sa.Column('status', sa.String(12), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_error', sa.String(300), nullable=True),
        sa.Column('remote_sha256', sa.String(64), nullable=True),
        sa.Column('synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_edge_sync')),
        schema='pacs')
    op.create_index(op.f('ix_edge_sync_tenant_id'), 'edge_sync', ['tenant_id'], schema='pacs')
    op.create_index('uq_pacs_edge_sync_instance', 'edge_sync', ['tenant_id', 'instance_id'], unique=True, schema='pacs')
    op.create_index('ix_pacs_edge_sync_due', 'edge_sync', ['tenant_id', 'status', 'next_attempt_at'], schema='pacs')
    app, service = f"{role_prefix}_app", f"{role_prefix}_service"
    for t in TENANT_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) "
                   f"WITH CHECK (tenant_id = {TENANT_EXPR})")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO {app}, {service}")


def downgrade(role_prefix: str = "vyonix") -> None:
    op.drop_table('edge_sync', schema='pacs')
