"""Administração global VYONIX: tipo da organização (instituição ou operadora VYONIX), dados cadastrais e módulos
contratados (intenção registrada no cadastro; o direito de uso continua vindo da licença assinada).

Revisão: core_0003
Anterior: core_0002
"""
from alembic import op
import sqlalchemy as sa


revision = 'core_0003'
down_revision = 'core_0002'
branch_labels = None
depends_on = None


def upgrade(role_prefix: str = "vyonix") -> None:
    add = lambda c: op.add_column('organizations', c, schema='tenancy')   # noqa: E731
    add(sa.Column('kind', sa.String(16), nullable=False, server_default='institution'))
    add(sa.Column('institution_type', sa.String(20), nullable=True))
    add(sa.Column('legal_name', sa.String(200), nullable=True))
    add(sa.Column('contact_name', sa.String(120), nullable=True))
    add(sa.Column('contact_email', sa.String(200), nullable=True))
    add(sa.Column('contact_phone', sa.String(40), nullable=True))
    add(sa.Column('contracted_modules', sa.JSON(), nullable=True))
    add(sa.Column('status_reason', sa.String(300), nullable=True))


def downgrade(role_prefix: str = "vyonix") -> None:
    for c in ('status_reason', 'contracted_modules', 'contact_phone', 'contact_email', 'contact_name', 'legal_name',
              'institution_type', 'kind'):
        op.drop_column('organizations', c, schema='tenancy')
