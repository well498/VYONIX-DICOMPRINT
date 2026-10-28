"""REPORT: reserva do exame pelo médico (atribuição do tipo "reserva" com validade) para a distribuição dinâmica.

Revisão: report_0010
Anterior: report_0009
"""
from alembic import op
import sqlalchemy as sa


revision = 'report_0010'
down_revision = 'report_0009'
branch_labels = None
depends_on = None


def upgrade(role_prefix: str = "vyonix") -> None:
    op.add_column('assignments', sa.Column('kind', sa.String(10), nullable=False, server_default='assigned'),
                  schema='report')
    op.add_column('assignments', sa.Column('reserved_until', sa.DateTime(timezone=True), nullable=True),
                  schema='report')


def downgrade(role_prefix: str = "vyonix") -> None:
    op.drop_column('assignments', 'reserved_until', schema='report')
    op.drop_column('assignments', 'kind', schema='report')
