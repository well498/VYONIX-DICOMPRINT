"""MISSÃO 2 (B-04): a tabela de controle das migrações (``platform.alembic_version``) deixa de ser alterável pelos
papéis da aplicação e de serviço — herdava INSERT/UPDATE/DELETE dos privilégios padrão do schema ``platform``.
Só o dono (usado pelo DEPLOY/CLI para migrar) altera a versão. Aditiva: nenhum dado é removido.

Revisão: core_0004
Anterior: core_0003
"""
from alembic import op


revision = 'core_0004'
down_revision = 'core_0003'
branch_labels = None
depends_on = None


def upgrade(role_prefix: str = "vyonix") -> None:
    for r in (f"{role_prefix}_app", f"{role_prefix}_service"):
        op.execute(f'REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON platform.alembic_version FROM "{r}"')


def downgrade(role_prefix: str = "vyonix") -> None:
    for r in (f"{role_prefix}_app", f"{role_prefix}_service"):
        op.execute(f'GRANT INSERT, UPDATE, DELETE ON platform.alembic_version TO "{r}"')
