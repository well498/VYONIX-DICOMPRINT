"""PACS: rotas de AE Title por organização (recepção por C-STORE no modo cloud) e estado global da sincronização.

Revisão: pacs_0002
Anterior: pacs_0001
"""
from alembic import op
import sqlalchemy as sa


revision = 'pacs_0002'
down_revision = 'pacs_0001'
branch_labels = None
depends_on = None

TENANT_TABLES = ("pacs.ae_routes",)
TENANT_EXPR = "nullif(current_setting('vyonix.tenant_id', true), '')::uuid"


def upgrade(role_prefix: str = "vyonix") -> None:
    op.create_table(
        'ae_routes',
        sa.Column('called_aet', sa.String(16), nullable=False),
        sa.Column('description', sa.String(200), nullable=True),
        sa.Column('created_by', sa.String(120), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_ae_routes')),
        schema='pacs')
    op.create_index(op.f('ix_ae_routes_tenant_id'), 'ae_routes', ['tenant_id'], schema='pacs')
    # Único no servidor inteiro (não por organização): um AE Title leva a uma só organização.
    op.create_index('uq_pacs_ae_routes_aet', 'ae_routes', ['called_aet'], unique=True, schema='pacs')
    op.create_table(
        'cloud_sync_state',
        sa.Column('backend', sa.String(20), nullable=False),
        sa.Column('last_seq', sa.BigInteger(), nullable=False),
        sa.Column('quarantined', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('backend', name=op.f('pk_cloud_sync_state')),
        schema='pacs')
    app, service = f"{role_prefix}_app", f"{role_prefix}_service"
    for t in TENANT_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) "
                   f"WITH CHECK (tenant_id = {TENANT_EXPR})")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON pacs.ae_routes TO {app}, {service}")
    # Estado global: só o papel de serviço (worker da nuvem); a aplicação não lê nem escreve.
    op.execute(f"REVOKE ALL ON pacs.cloud_sync_state FROM {app}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON pacs.cloud_sync_state TO {service}")


def downgrade(role_prefix: str = "vyonix") -> None:
    op.drop_table('cloud_sync_state', schema='pacs')
    op.drop_table('ae_routes', schema='pacs')
