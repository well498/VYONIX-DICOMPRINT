"""RIS inicial: agendamentos (passos de procedimento agendados) para a Modality Worklist.

Revisão: ris_0001
Anterior: — (ramo próprio, depende do core_0001)
"""
from alembic import op
import sqlalchemy as sa


revision = 'ris_0001'
down_revision = None
branch_labels = ('ris',)
depends_on = 'core_0001'

TENANT_TABLES = ("ris.schedules",)
TENANT_EXPR = "nullif(current_setting('vyonix.tenant_id', true), '')::uuid"


def upgrade(role_prefix: str = "vyonix") -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS ris")
    op.create_table(
        'schedules',
        sa.Column('order_id', sa.Uuid(), nullable=False),
        sa.Column('sps_id', sa.String(16), nullable=False),
        sa.Column('study_instance_uid', sa.String(64), nullable=False),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('modality', sa.String(16), nullable=False),
        sa.Column('station_aet', sa.String(16), nullable=True),
        sa.Column('room', sa.String(64), nullable=True),
        sa.Column('description', sa.String(64), nullable=True),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('created_by', sa.String(120), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['order_id'], ['clinical.orders.id'], name=op.f('fk_schedules_order_id')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_schedules')),
        schema='ris')
    op.create_index(op.f('ix_schedules_tenant_id'), 'schedules', ['tenant_id'], schema='ris')
    op.create_index(op.f('ix_schedules_order_id'), 'schedules', ['order_id'], schema='ris')
    op.create_index('uq_ris_schedules_sps', 'schedules', ['tenant_id', 'sps_id'], unique=True, schema='ris')
    op.create_index('uq_ris_schedules_study_uid', 'schedules', ['tenant_id', 'study_instance_uid'], unique=True,
                    schema='ris')
    op.create_index('ix_ris_schedules_when', 'schedules', ['tenant_id', 'scheduled_at'], schema='ris')
    app, service = f"{role_prefix}_app", f"{role_prefix}_service"
    for t in TENANT_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) "
                   f"WITH CHECK (tenant_id = {TENANT_EXPR})")
    op.execute(f"GRANT USAGE ON SCHEMA ris TO {app}, {service}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ris TO {app}, {service}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA ris GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES "
               f"TO {app}, {service}")


def downgrade(role_prefix: str = "vyonix") -> None:
    op.drop_table('schedules', schema='ris')
    op.execute("DROP SCHEMA IF EXISTS ris")
