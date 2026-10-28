"""RIS: cadastro de salas (com modalidade e estação padrão) para o agendamento.

Revisão: ris_0004
Anterior: ris_0003
"""
from alembic import op
import sqlalchemy as sa


revision = 'ris_0004'
down_revision = 'ris_0003'
branch_labels = None
depends_on = None

TENANT_TABLES = ("ris.rooms",)
TENANT_EXPR = "nullif(current_setting('vyonix.tenant_id', true), '')::uuid"


def upgrade(role_prefix: str = "vyonix") -> None:
    op.create_table(
        'rooms',
        sa.Column('name', sa.String(64), nullable=False), sa.Column('modality', sa.String(16), nullable=True),
        sa.Column('station_aet', sa.String(16), nullable=True),
        sa.Column('default_duration_min', sa.Integer(), nullable=False, server_default='15'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('id', sa.Uuid(), nullable=False), sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_rooms')), schema='ris')
    op.create_index(op.f('ix_rooms_tenant_id'), 'rooms', ['tenant_id'], schema='ris')
    op.create_index('uq_ris_rooms_name', 'rooms', ['tenant_id', sa.text('lower(name)')], unique=True, schema='ris')
    for t in TENANT_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) "
                   f"WITH CHECK (tenant_id = {TENANT_EXPR})")


def downgrade(role_prefix: str = "vyonix") -> None:
    op.drop_table('rooms', schema='ris')
