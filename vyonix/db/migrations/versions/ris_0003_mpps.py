"""RIS: vínculo do agendamento com o MPPS (Modality Performed Procedure Step) enviado pela modalidade.

Revisão: ris_0003
Anterior: ris_0002
"""
from alembic import op
import sqlalchemy as sa


revision = 'ris_0003'
down_revision = 'ris_0002'
branch_labels = None
depends_on = None


def upgrade(role_prefix: str = "vyonix") -> None:
    op.add_column('schedules', sa.Column('mpps_uid', sa.String(64), nullable=True), schema='ris')
    op.add_column('schedules', sa.Column('mpps_status', sa.String(16), nullable=True), schema='ris')
    op.create_index('uq_ris_schedules_mpps', 'schedules', ['tenant_id', 'mpps_uid'], unique=True, schema='ris',
                    postgresql_where=sa.text('mpps_uid IS NOT NULL'))


def downgrade(role_prefix: str = "vyonix") -> None:
    op.drop_index('uq_ris_schedules_mpps', table_name='schedules', schema='ris')
    op.drop_column('schedules', 'mpps_status', schema='ris')
    op.drop_column('schedules', 'mpps_uid', schema='ris')
