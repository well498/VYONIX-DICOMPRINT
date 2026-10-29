"""PACS: gestão de nós DICOM — cadastro do equipamento (fabricante, modelo, modalidade, unidade), serviços permitidos
(recepção por C-STORE), status (ativo, último contato, C-ECHO, último erro), histórico de conexões e retenção de
recepções de equipamentos não autorizados (sem exclusão).

Revisão: pacs_0006
Anterior: pacs_0005
"""
from alembic import op
import sqlalchemy as sa


revision = 'pacs_0006'
down_revision = 'pacs_0005'
branch_labels = None
depends_on = None

TENANT_TABLES = ("pacs.dicom_events", "pacs.store_holds")
TENANT_EXPR = "nullif(current_setting('vyonix.tenant_id', true), '')::uuid"


def _base():
    return [sa.Column('id', sa.Uuid(), nullable=False),
            sa.Column('tenant_id', sa.Uuid(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('row_version', sa.Integer(), nullable=False)]


def upgrade(role_prefix: str = "vyonix") -> None:
    for col in (sa.Column('name', sa.String(120), nullable=True),
                sa.Column('manufacturer', sa.String(80), nullable=True),
                sa.Column('model', sa.String(80), nullable=True),
                sa.Column('modality', sa.String(16), nullable=True),
                sa.Column('site_id', sa.Uuid(), nullable=True),
                sa.Column('can_store', sa.Boolean(), nullable=False, server_default=sa.text('false')),
                sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
                sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
                sa.Column('last_echo_at', sa.DateTime(timezone=True), nullable=True),
                sa.Column('last_echo_ok', sa.Boolean(), nullable=True),
                sa.Column('last_error', sa.String(300), nullable=True),
                sa.Column('last_error_at', sa.DateTime(timezone=True), nullable=True)):
        op.add_column('dicom_nodes', col, schema='pacs')
    op.create_table(
        'dicom_events',
        sa.Column('node_id', sa.Uuid(), nullable=True),
        sa.Column('direction', sa.String(3), nullable=False),
        sa.Column('service', sa.String(16), nullable=False),
        sa.Column('outcome', sa.String(12), nullable=False),
        sa.Column('calling_ae', sa.String(16), nullable=True),
        sa.Column('called_ae', sa.String(16), nullable=True),
        sa.Column('address', sa.String(64), nullable=True),
        sa.Column('detail', sa.String(300), nullable=True),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.Column('last_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        *_base(),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_dicom_events')),
        schema='pacs')
    op.create_index(op.f('ix_dicom_events_tenant_id'), 'dicom_events', ['tenant_id'], schema='pacs')
    op.create_index('ix_pacs_dicom_events_at', 'dicom_events', ['tenant_id', 'last_at'], schema='pacs')
    op.create_table(
        'store_holds',
        sa.Column('backend', sa.String(20), nullable=False),
        sa.Column('backend_id', sa.String(80), nullable=False),
        sa.Column('remote_aet', sa.String(16), nullable=True),
        sa.Column('remote_ip', sa.String(64), nullable=True),
        sa.Column('called_aet', sa.String(16), nullable=True),
        sa.Column('reason', sa.String(200), nullable=False),
        sa.Column('status', sa.String(12), nullable=False),
        sa.Column('decided_by', sa.String(120), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decision_note', sa.String(300), nullable=True),
        *_base(),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_store_holds')),
        schema='pacs')
    op.create_index(op.f('ix_store_holds_tenant_id'), 'store_holds', ['tenant_id'], schema='pacs')
    op.create_index('uq_pacs_store_holds', 'store_holds', ['tenant_id', 'backend', 'backend_id'], unique=True,
                    schema='pacs')
    app, service = f"{role_prefix}_app", f"{role_prefix}_service"
    for t in TENANT_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) "
                   f"WITH CHECK (tenant_id = {TENANT_EXPR})")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO {app}, {service}")


def downgrade(role_prefix: str = "vyonix") -> None:
    op.drop_table('store_holds', schema='pacs')
    op.drop_table('dicom_events', schema='pacs')
    for c in ('last_error_at', 'last_error', 'last_echo_ok', 'last_echo_at', 'last_seen_at', 'enabled', 'can_store',
              'site_id', 'modality', 'model', 'manufacturer', 'name'):
        op.drop_column('dicom_nodes', c, schema='pacs')
