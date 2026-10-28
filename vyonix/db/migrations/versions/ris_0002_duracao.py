"""RIS: duração prevista do exame (minutos), usada para impedir horários sobrepostos na mesma estação ou sala.

Revisão: ris_0002
Anterior: ris_0001
Agendamentos existentes recebem 15 minutos (padrão); nenhum dado é apagado.
"""
from alembic import op
import sqlalchemy as sa


revision = 'ris_0002'
down_revision = 'ris_0001'
branch_labels = None
depends_on = None


def upgrade(role_prefix: str = "vyonix") -> None:
    op.add_column('schedules', sa.Column('duration_min', sa.Integer(), nullable=False, server_default='15'),
                  schema='ris')


def downgrade(role_prefix: str = "vyonix") -> None:
    op.drop_column('schedules', 'duration_min', schema='ris')
