"""REPORT: comunicação de achados críticos (pendência aberta na liberação, encerrada com o registro de quem foi
avisado, por quem e quando).

Revisão: report_0002
Anterior: report_0001
"""
from alembic import op
import sqlalchemy as sa


revision = 'report_0002'
down_revision = 'report_0001'
branch_labels = None
depends_on = None

TENANT_TABLES = ("report.critical_alerts",)
TENANT_EXPR = "nullif(current_setting('vyonix.tenant_id', true), '')::uuid"


def upgrade(role_prefix: str = "vyonix") -> None:
    op.create_table(
        'critical_alerts',
        sa.Column('report_id', sa.Uuid(), nullable=False), sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('note', sa.String(300), nullable=True), sa.Column('status', sa.String(12), nullable=False),
        sa.Column('notified_to', sa.String(200), nullable=True), sa.Column('channel', sa.String(40), nullable=True),
        sa.Column('ack_note', sa.String(500), nullable=True), sa.Column('ack_by', sa.String(120), nullable=True),
        sa.Column('ack_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False), sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['report_id'], ['report.reports.id'], name=op.f('fk_critical_alerts_report_id')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_critical_alerts')), schema='report')
    op.create_index(op.f('ix_critical_alerts_tenant_id'), 'critical_alerts', ['tenant_id'], schema='report')
    op.create_index('ix_report_critical_open', 'critical_alerts', ['tenant_id', 'status'], schema='report')
    for t in TENANT_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) "
                   f"WITH CHECK (tenant_id = {TENANT_EXPR})")


def downgrade(role_prefix: str = "vyonix") -> None:
    op.drop_table('critical_alerts', schema='report')
