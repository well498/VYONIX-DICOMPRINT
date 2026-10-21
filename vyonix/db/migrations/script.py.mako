"""${message}

Revisão: ${up_revision}
Anterior: ${down_revision | comma,n}
"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade(role_prefix: str = "vyonix") -> None:
    ${upgrades if upgrades else "pass"}


def downgrade(role_prefix: str = "vyonix") -> None:
    ${downgrades if downgrades else "pass"}
