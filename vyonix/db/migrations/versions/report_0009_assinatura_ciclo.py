"""REPORT: ciclo de vida da imagem da assinatura manuscrita (pendente → ativa → substituída/revogada/excluída), quem
enviou (o médico ou administrador delegado por ele), confirmação do médico, tratamento aplicado; delegado de envio
no cadastro do médico; bloco de identificação profissional configurável na versão do modelo.

Revisão: report_0009
Anterior: report_0008
"""
from alembic import op
import sqlalchemy as sa


revision = 'report_0009'
down_revision = 'report_0008'
branch_labels = None
depends_on = None


def upgrade(role_prefix: str = "vyonix") -> None:
    add = lambda t, c: op.add_column(t, c, schema='report')  # noqa: E731
    add('signature_images', sa.Column('status', sa.String(12), nullable=False, server_default='active'))
    add('signature_images', sa.Column('media_type', sa.String(20), nullable=True))
    add('signature_images', sa.Column('uploaded_by', sa.String(120), nullable=True))
    add('signature_images', sa.Column('uploaded_by_id', sa.Uuid(), nullable=True))
    add('signature_images', sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True))
    add('signature_images', sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True))
    add('signature_images', sa.Column('processing', sa.JSON(), nullable=True))
    op.execute("UPDATE report.signature_images SET status = CASE WHEN active THEN 'active' ELSE 'replaced' END")
    add('physicians', sa.Column('signature_delegate_user_id', sa.Uuid(), nullable=True))
    add('template_versions', sa.Column('signature_block', sa.JSON(), nullable=True))


def downgrade(role_prefix: str = "vyonix") -> None:
    op.drop_column('template_versions', 'signature_block', schema='report')
    op.drop_column('physicians', 'signature_delegate_user_id', schema='report')
    for c in ('processing', 'ended_at', 'confirmed_at', 'uploaded_by_id', 'uploaded_by', 'media_type', 'status'):
        op.drop_column('signature_images', c, schema='report')
