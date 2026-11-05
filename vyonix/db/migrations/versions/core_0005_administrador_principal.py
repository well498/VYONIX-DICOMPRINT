"""Administrador principal e dados de contato do usuário (decisão do proprietário, 05/11/2026).

* ``auth.users.main_admin``: só o administrador principal adiciona ou remove perfis; até 3 por instituição.
  A marcação inicial (o administrador mais antigo de cada instituição) é feita pela aplicação ao atualizar
  (``tenancy.refresh`` → ``auth.ensure_main_admin``), porque a migração não enxerga as linhas sob RLS.
* ``auth.users.phone`` e ``auth.users.professional_reg`` (CRTR, matrícula): opcionais.

Aditiva: nenhuma coluna ou dado é removido.

Revisão: core_0005
Anterior: core_0004
"""
import sqlalchemy as sa
from alembic import op


revision = 'core_0005'
down_revision = 'core_0004'
branch_labels = None
depends_on = None


def upgrade(role_prefix: str = "vyonix") -> None:
    op.add_column("users", sa.Column("main_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
                  schema="auth")
    op.add_column("users", sa.Column("phone", sa.String(30), nullable=True), schema="auth")
    op.add_column("users", sa.Column("professional_reg", sa.String(40), nullable=True), schema="auth")


def downgrade(role_prefix: str = "vyonix") -> None:
    for c in ("professional_reg", "phone", "main_admin"):
        op.drop_column("users", c, schema="auth")
