"""REPORT / TELELAUDO T7: fila de laudos — atribuição do exame a um médico, prioridade e prazo (SLA).

Revisão: report_0008
Anterior: report_0007
"""
from alembic import op
import sqlalchemy as sa


revision = 'report_0008'
down_revision = 'report_0007'
branch_labels = None
depends_on = None

TENANT_TABLES = ("report.assignments",)
TENANT_EXPR = "nullif(current_setting('vyonix.tenant_id', true), '')::uuid"


def upgrade(role_prefix: str = "vyonix") -> None:
    op.create_table(
        'assignments',
        sa.Column('study_id', sa.Uuid(), nullable=False), sa.Column('physician_id', sa.Uuid(), nullable=False),
        sa.Column('priority', sa.String(10), nullable=False), sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(12), nullable=False), sa.Column('assigned_by', sa.String(120), nullable=False),
        sa.Column('done_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False), sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['study_id'], ['clinical.studies.id'], name=op.f('fk_assignments_study_id')),
        sa.ForeignKeyConstraint(['physician_id'], ['report.physicians.id'], name=op.f('fk_assignments_physician_id')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_assignments')), schema='report')
    op.create_index(op.f('ix_assignments_tenant_id'), 'assignments', ['tenant_id'], schema='report')
    op.create_index('uq_report_assignment_open', 'assignments', ['tenant_id', 'study_id'], unique=True,
                    schema='report', postgresql_where=sa.text("status = 'open'"))
    for t in TENANT_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) "
                   f"WITH CHECK (tenant_id = {TENANT_EXPR})")


def downgrade(role_prefix: str = "vyonix") -> None:
    op.drop_table('assignments', schema='report')
