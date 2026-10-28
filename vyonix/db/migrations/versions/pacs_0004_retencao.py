"""PACS: guarda obrigatória por estudo (retenção). O relatório de retenção só lista; nada é excluído.

Revisão: pacs_0004
Anterior: pacs_0003
"""
from alembic import op
import sqlalchemy as sa


revision = 'pacs_0004'
down_revision = 'pacs_0003'
branch_labels = None
depends_on = None


def upgrade(role_prefix: str = "vyonix") -> None:
    op.add_column('studies', sa.Column('retention_hold', sa.Boolean(), nullable=False, server_default='false'),
                  schema='pacs')
    op.add_column('studies', sa.Column('retention_hold_reason', sa.String(300), nullable=True), schema='pacs')


def downgrade(role_prefix: str = "vyonix") -> None:
    op.drop_column('studies', 'retention_hold_reason', schema='pacs')
    op.drop_column('studies', 'retention_hold', schema='pacs')
