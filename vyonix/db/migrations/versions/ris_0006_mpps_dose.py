"""RIS: resumo do MPPS informado pela modalidade — séries realizadas (descrição, protocolo, quantidade de imagens) e
dados de dose do módulo Radiation Dose do MPPS (como informados; não validados).

Revisão: ris_0006
Anterior: ris_0005
"""
from alembic import op
import sqlalchemy as sa


revision = 'ris_0006'
down_revision = 'ris_0005'
branch_labels = None
depends_on = None


def upgrade(role_prefix: str = "vyonix") -> None:
    op.add_column('schedules', sa.Column('mpps_summary', sa.JSON(), nullable=True), schema='ris')


def downgrade(role_prefix: str = "vyonix") -> None:
    op.drop_column('schedules', 'mpps_summary', schema='ris')
