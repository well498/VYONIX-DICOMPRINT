"""PACS: regras de encaminhamento automático e fila de envios (C-STORE) com novas tentativas.

Revisão: pacs_0007
Anterior: pacs_0006
"""
from alembic import op
import sqlalchemy as sa


revision = 'pacs_0007'
down_revision = 'pacs_0006'
branch_labels = None
depends_on = None

TENANT_TABLES = ("pacs.forward_rules", "pacs.forward_jobs")
TENANT_EXPR = "nullif(current_setting('vyonix.tenant_id', true), '')::uuid"


def _base():
    return [sa.Column('id', sa.Uuid(), nullable=False),
            sa.Column('tenant_id', sa.Uuid(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('row_version', sa.Integer(), nullable=False)]


def upgrade(role_prefix: str = "vyonix") -> None:
    op.create_table(
        'forward_rules',
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('source', sa.String(16), nullable=True),
        sa.Column('modality', sa.String(16), nullable=True),
        sa.Column('destination_node_id', sa.Uuid(), nullable=False),
        sa.Column('created_by', sa.String(120), nullable=False),
        *_base(),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_forward_rules')),
        schema='pacs')
    op.create_index(op.f('ix_forward_rules_tenant_id'), 'forward_rules', ['tenant_id'], schema='pacs')
    op.create_table(
        'forward_jobs',
        sa.Column('rule_id', sa.Uuid(), nullable=True),
        sa.Column('study_id', sa.Uuid(), nullable=False),
        sa.Column('destination_node_id', sa.Uuid(), nullable=False),
        sa.Column('status', sa.String(12), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('instances', sa.Integer(), nullable=False),
        sa.Column('sent', sa.Integer(), nullable=False),
        sa.Column('integrity_failures', sa.Integer(), nullable=False),
        sa.Column('last_error', sa.String(300), nullable=True),
        sa.Column('done_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('requested_by', sa.String(120), nullable=False),
        *_base(),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_forward_jobs')),
        schema='pacs')
    op.create_index(op.f('ix_forward_jobs_tenant_id'), 'forward_jobs', ['tenant_id'], schema='pacs')
    op.create_index('ix_pacs_forward_jobs_due', 'forward_jobs', ['tenant_id', 'status', 'next_attempt_at'],
                    schema='pacs')
    app, service = f"{role_prefix}_app", f"{role_prefix}_service"
    for t in TENANT_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) "
                   f"WITH CHECK (tenant_id = {TENANT_EXPR})")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO {app}, {service}")


def downgrade(role_prefix: str = "vyonix") -> None:
    op.drop_table('forward_jobs', schema='pacs')
    op.drop_table('forward_rules', schema='pacs')
