"""Diretório global de logins (login simplificado: só usuário e senha no servidor com várias instituições).

Preenchido com os logins existentes que já são únicos entre as organizações. Logins repetidos em duas ou mais
organizações **não** entram (nada é alterado nas contas): continuam entrando com o código da organização até
serem renomeados — ``vyonix login-conflicts`` lista quais são.

Revisão: core_0002
Anterior: core_0001
"""
from alembic import op
import sqlalchemy as sa


revision = 'core_0002'
down_revision = 'core_0001'
branch_labels = None
depends_on = None


def upgrade(role_prefix: str = "vyonix") -> None:
    op.create_table(
        'login_directory',
        sa.Column('login', sa.String(60), nullable=False),
        sa.Column('org_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('login', name=op.f('pk_login_directory')),
        schema='auth')
    op.create_index('uq_login_directory_user', 'login_directory', ['user_id'], unique=True, schema='auth')
    app, service = f"{role_prefix}_app", f"{role_prefix}_service"
    op.execute(f"REVOKE ALL ON auth.login_directory FROM {app}")
    op.execute(f"GRANT SELECT, INSERT, DELETE ON auth.login_directory TO {service}")
    op.execute("""INSERT INTO auth.login_directory (login, org_id, user_id)
                  SELECT lower(u.username), u.tenant_id, u.id FROM auth.users u
                  WHERE lower(u.username) IN (SELECT lower(username) FROM auth.users
                                              GROUP BY lower(username) HAVING count(*) = 1)""")


def downgrade(role_prefix: str = "vyonix") -> None:
    op.drop_table('login_directory', schema='auth')
