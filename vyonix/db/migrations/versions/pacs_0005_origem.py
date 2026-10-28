"""PACS: equipamento de origem do estudo (AE Title de quem enviou por DICOM), para filtros da Central de Exames.

Revisão: pacs_0005
Anterior: pacs_0004
"""
from alembic import op
import sqlalchemy as sa


revision = 'pacs_0005'
down_revision = 'pacs_0004'
branch_labels = None
depends_on = None


def upgrade(role_prefix: str = "vyonix") -> None:
    op.add_column('studies', sa.Column('source_ae', sa.String(16), nullable=True), schema='pacs')


def downgrade(role_prefix: str = "vyonix") -> None:
    op.drop_column('studies', 'source_ae', schema='pacs')
