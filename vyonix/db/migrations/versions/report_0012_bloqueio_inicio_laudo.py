"""REPORT: registro permanente do início da elaboração do laudo (bloqueia troca de médico e prioridade).

Aditiva. O aplicativo só pode INSERIR e LER (sem UPDATE/DELETE), para que o bloqueio não seja removido por mudança
de status, fechamento do editor ou operação concorrente. Exames que já têm laudo (rascunho, revisão ou liberado)
recebem o registro a partir do próprio laudo (origem ``migracao``).

Revisão: report_0012
Anterior: report_0011
"""
from alembic import op
import sqlalchemy as sa


revision = 'report_0012'
down_revision = 'report_0011'
branch_labels = None
depends_on = None

TENANT_TABLES = ("report.report_starts",)
TENANT_EXPR = "nullif(current_setting('vyonix.tenant_id', true), '')::uuid"


def upgrade(role_prefix: str = "vyonix") -> None:
    op.create_table(
        'report_starts',
        sa.Column('study_id', sa.Uuid(), sa.ForeignKey('clinical.studies.id'), nullable=False),
        sa.Column('report_id', sa.Uuid(), sa.ForeignKey('report.reports.id'), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_by', sa.String(120), nullable=False),
        sa.Column('started_by_id', sa.Uuid(), nullable=True),
        sa.Column('physician_id', sa.Uuid(), nullable=True),
        sa.Column('physician_name', sa.String(160), nullable=True),
        sa.Column('priority', sa.String(10), nullable=True),
        sa.Column('origin', sa.String(12), nullable=False, server_default='editor'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_report_starts')),
        schema='report')
    op.create_index(op.f('ix_report_starts_tenant_id'), 'report_starts', ['tenant_id'], schema='report')
    op.create_index('uq_report_report_starts_study', 'report_starts', ['tenant_id', 'study_id'], unique=True,
                    schema='report')
    # exames que já têm laudo: o início é o próprio laudo (sem perder nada; nenhum dado existente é alterado)
    op.execute("""
        INSERT INTO report.report_starts (id, tenant_id, study_id, report_id, started_at, started_by, priority,
                                          origin, row_version)
        SELECT gen_random_uuid(), r.tenant_id, r.study_id, r.id, r.created_at, r.author,
               (SELECT a.priority FROM report.assignments a WHERE a.study_id = r.study_id
                 ORDER BY a.created_at DESC LIMIT 1), 'migracao', 1
          FROM report.reports r
         WHERE NOT EXISTS (SELECT 1 FROM report.report_starts x WHERE x.study_id = r.study_id
                                                                 AND x.tenant_id = r.tenant_id)""")
    t = TENANT_TABLES[0]
    app, service = f"{role_prefix}_app", f"{role_prefix}_service"
    op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) "
               f"WITH CHECK (tenant_id = {TENANT_EXPR})")
    # sem UPDATE/DELETE/TRUNCATE: bloqueio permanente (revoga também privilégios padrão herdados do esquema)
    op.execute(f"REVOKE ALL ON {t} FROM {app}, {service}")
    op.execute(f"GRANT SELECT, INSERT ON {t} TO {app}, {service}")


def downgrade(role_prefix: str = "vyonix") -> None:
    op.drop_table('report_starts', schema='report')
