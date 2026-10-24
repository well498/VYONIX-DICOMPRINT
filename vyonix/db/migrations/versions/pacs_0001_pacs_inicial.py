"""PACS inicial: índice de estudos, séries e instâncias por organização, com row level security forçado.

Revisão: pacs_0001
Anterior: — (ramo próprio, depende do core_0001)
"""
from alembic import op
import sqlalchemy as sa


revision = 'pacs_0001'
down_revision = None
branch_labels = ('pacs',)
depends_on = 'core_0001'

TENANT_TABLES = ("pacs.studies", "pacs.series", "pacs.instances", "pacs.sync_state")
TENANT_EXPR = "nullif(current_setting('vyonix.tenant_id', true), '')::uuid"


def _common():
    return [sa.Column('id', sa.Uuid(), nullable=False),
            sa.Column('tenant_id', sa.Uuid(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('row_version', sa.Integer(), nullable=False)]


def upgrade(role_prefix: str = "vyonix") -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS pacs")
    op.create_table(
        'studies',
        sa.Column('study_uid', sa.String(64), nullable=False),
        sa.Column('patient_id', sa.String(64), nullable=False),
        sa.Column('patient_name', sa.String(200), nullable=False),
        sa.Column('patient_birth_date', sa.Date(), nullable=True),
        sa.Column('patient_sex', sa.String(1), nullable=True),
        sa.Column('study_date', sa.Date(), nullable=True),
        sa.Column('study_time', sa.String(16), nullable=True),
        sa.Column('accession', sa.String(32), nullable=True),
        sa.Column('description', sa.String(200), nullable=True),
        sa.Column('referring_physician', sa.String(200), nullable=True),
        sa.Column('dicom_study_id', sa.String(16), nullable=True),
        sa.Column('clinical_study_id', sa.Uuid(), nullable=True),
        sa.Column('last_received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        *_common(),
        sa.ForeignKeyConstraint(['clinical_study_id'], ['clinical.studies.id'],
                                name=op.f('fk_studies_clinical_study_id')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_studies')),
        schema='pacs')
    op.create_index(op.f('ix_studies_tenant_id'), 'studies', ['tenant_id'], schema='pacs')
    op.create_index('uq_pacs_studies_uid', 'studies', ['tenant_id', 'study_uid'], unique=True, schema='pacs')
    op.create_index('ix_pacs_studies_patient', 'studies', ['tenant_id', 'patient_id'], schema='pacs')
    op.create_index('ix_pacs_studies_date', 'studies', ['tenant_id', 'study_date'], schema='pacs')

    op.create_table(
        'series',
        sa.Column('study_id', sa.Uuid(), nullable=False),
        sa.Column('series_uid', sa.String(64), nullable=False),
        sa.Column('modality', sa.String(16), nullable=True),
        sa.Column('series_number', sa.Integer(), nullable=True),
        sa.Column('description', sa.String(200), nullable=True),
        *_common(),
        sa.ForeignKeyConstraint(['study_id'], ['pacs.studies.id'], name=op.f('fk_series_study_id')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_series')),
        schema='pacs')
    op.create_index(op.f('ix_series_tenant_id'), 'series', ['tenant_id'], schema='pacs')
    op.create_index(op.f('ix_series_study_id'), 'series', ['study_id'], schema='pacs')
    op.create_index('uq_pacs_series_uid', 'series', ['tenant_id', 'series_uid'], unique=True, schema='pacs')

    op.create_table(
        'instances',
        sa.Column('series_id', sa.Uuid(), nullable=False),
        sa.Column('study_id', sa.Uuid(), nullable=False),
        sa.Column('sop_uid', sa.String(64), nullable=False),
        sa.Column('sop_class_uid', sa.String(64), nullable=False),
        sa.Column('transfer_syntax', sa.String(64), nullable=False),
        sa.Column('instance_number', sa.Integer(), nullable=True),
        sa.Column('rows', sa.Integer(), nullable=True),
        sa.Column('columns', sa.Integer(), nullable=True),
        sa.Column('frames', sa.Integer(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('backend', sa.String(20), nullable=False),
        sa.Column('backend_id', sa.String(80), nullable=False),
        sa.Column('received_via', sa.String(10), nullable=False),
        *_common(),
        sa.ForeignKeyConstraint(['series_id'], ['pacs.series.id'], name=op.f('fk_instances_series_id')),
        sa.ForeignKeyConstraint(['study_id'], ['pacs.studies.id'], name=op.f('fk_instances_study_id')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_instances')),
        schema='pacs')
    op.create_index(op.f('ix_instances_tenant_id'), 'instances', ['tenant_id'], schema='pacs')
    op.create_index(op.f('ix_instances_series_id'), 'instances', ['series_id'], schema='pacs')
    op.create_index(op.f('ix_instances_study_id'), 'instances', ['study_id'], schema='pacs')
    op.create_index('uq_pacs_instances_uid', 'instances', ['tenant_id', 'sop_uid'], unique=True, schema='pacs')

    op.create_table(
        'sync_state',
        sa.Column('backend', sa.String(20), nullable=False),
        sa.Column('last_seq', sa.BigInteger(), nullable=False),
        *_common(),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_sync_state')),
        schema='pacs')
    op.create_index(op.f('ix_sync_state_tenant_id'), 'sync_state', ['tenant_id'], schema='pacs')
    op.create_index('uq_pacs_sync_backend', 'sync_state', ['tenant_id', 'backend'], unique=True, schema='pacs')

    secure(role_prefix)


def secure(prefix: str) -> None:
    app, service = f"{prefix}_app", f"{prefix}_service"
    for t in TENANT_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) "
                   f"WITH CHECK (tenant_id = {TENANT_EXPR})")
    op.execute(f"GRANT USAGE ON SCHEMA pacs TO {app}, {service}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA pacs TO {app}, {service}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA pacs GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES "
               f"TO {app}, {service}")


def downgrade(role_prefix: str = "vyonix") -> None:
    for t in ("instances", "series", "sync_state", "studies"):
        op.drop_table(t, schema='pacs')
    op.execute("DROP SCHEMA IF EXISTS pacs")
