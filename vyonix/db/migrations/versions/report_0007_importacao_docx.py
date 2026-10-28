"""REPORT / TELELAUDO T6: relatório da importação DOCX guardado na versão do modelo (incompatibilidades, campos
mapeados, cabeçalho e rodapé sugeridos) para a conferência antes da publicação.

Revisão: report_0007
Anterior: report_0006
"""
from alembic import op
import sqlalchemy as sa


revision = 'report_0007'
down_revision = 'report_0006'
branch_labels = None
depends_on = None


def upgrade(role_prefix: str = "vyonix") -> None:
    op.add_column('template_versions', sa.Column('import_report', sa.JSON(), nullable=True), schema='report')


def downgrade(role_prefix: str = "vyonix") -> None:
    op.drop_column('template_versions', 'import_report', schema='report')
