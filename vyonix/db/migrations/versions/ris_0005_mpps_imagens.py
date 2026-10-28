"""RIS: imagens informadas pela modalidade no MPPS (PerformedSeriesSequence), para conferir se o PACS recebeu tudo.

Revisão: ris_0005
Anterior: ris_0004
"""
from alembic import op
import sqlalchemy as sa


revision = 'ris_0005'
down_revision = 'ris_0004'
branch_labels = None
depends_on = None


def upgrade(role_prefix: str = "vyonix") -> None:
    op.add_column('schedules', sa.Column('mpps_performed', sa.JSON(), nullable=True), schema='ris')


def downgrade(role_prefix: str = "vyonix") -> None:
    op.drop_column('schedules', 'mpps_performed', schema='ris')
