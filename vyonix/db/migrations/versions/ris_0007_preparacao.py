"""RIS: preparação técnica dos estudos (Central de Exames / Painel do Técnico) — estado, checklist, anexos
cifrados, comentários com leitura, suspeitas técnicas e compartilhamento temporário.

Revisão: ris_0007
Anterior: ris_0006
"""
from alembic import op
import sqlalchemy as sa


revision = 'ris_0007'
down_revision = 'ris_0006'
branch_labels = None
depends_on = None

TENANT_TABLES = ("ris.exam_preps", "ris.exam_attachments", "ris.exam_comments", "ris.exam_comment_reads", "ris.exam_flags", "ris.exam_shares",)
TENANT_EXPR = "nullif(current_setting('vyonix.tenant_id', true), '')::uuid"


def upgrade(role_prefix: str = "vyonix") -> None:
    op.create_table(
        'exam_preps',
        sa.Column('study_id', sa.Uuid(), sa.ForeignKey('clinical.studies.id'), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('checklist', sa.JSON(), nullable=False),
        sa.Column('priority', sa.String(10), nullable=True),
        sa.Column('reason', sa.String(300), nullable=True),
        sa.Column('forwarded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('forwarded_by', sa.String(120), nullable=True),
        sa.Column('duplicate_of', sa.Uuid(), nullable=True),
        sa.Column('duplicate_checked', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_exam_preps')),
        schema='ris')
    op.create_index(op.f('ix_exam_preps_tenant_id'), 'exam_preps', ['tenant_id'], schema='ris')
    op.create_table(
        'exam_attachments',
        sa.Column('study_id', sa.Uuid(), sa.ForeignKey('clinical.studies.id'), nullable=False),
        sa.Column('kind', sa.String(10), nullable=False),
        sa.Column('media_type', sa.String(40), nullable=False),
        sa.Column('filename', sa.String(120), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('nonce', sa.LargeBinary(), nullable=False),
        sa.Column('ciphertext', sa.LargeBinary(), nullable=False),
        sa.Column('created_by', sa.String(120), nullable=False),
        sa.Column('created_by_id', sa.Uuid(), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_exam_attachments')),
        schema='ris')
    op.create_index(op.f('ix_exam_attachments_tenant_id'), 'exam_attachments', ['tenant_id'], schema='ris')
    op.create_table(
        'exam_comments',
        sa.Column('study_id', sa.Uuid(), sa.ForeignKey('clinical.studies.id'), nullable=False),
        sa.Column('author', sa.String(120), nullable=False),
        sa.Column('author_id', sa.Uuid(), nullable=True),
        sa.Column('text', sa.String(2000), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_exam_comments')),
        schema='ris')
    op.create_index(op.f('ix_exam_comments_tenant_id'), 'exam_comments', ['tenant_id'], schema='ris')
    op.create_table(
        'exam_comment_reads',
        sa.Column('study_id', sa.Uuid(), sa.ForeignKey('clinical.studies.id'), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('last_read_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_exam_comment_reads')),
        schema='ris')
    op.create_index(op.f('ix_exam_comment_reads_tenant_id'), 'exam_comment_reads', ['tenant_id'], schema='ris')
    op.create_table(
        'exam_flags',
        sa.Column('study_id', sa.Uuid(), sa.ForeignKey('clinical.studies.id'), nullable=False),
        sa.Column('code', sa.String(30), nullable=False),
        sa.Column('note', sa.String(500), nullable=True),
        sa.Column('status', sa.String(10), nullable=False),
        sa.Column('created_by', sa.String(120), nullable=False),
        sa.Column('resolved_by', sa.String(120), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_exam_flags')),
        schema='ris')
    op.create_index(op.f('ix_exam_flags_tenant_id'), 'exam_flags', ['tenant_id'], schema='ris')
    op.create_table(
        'exam_shares',
        sa.Column('study_id', sa.Uuid(), sa.ForeignKey('clinical.studies.id'), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('scope', sa.String(10), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by', sa.String(120), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_exam_shares')),
        schema='ris')
    op.create_index(op.f('ix_exam_shares_tenant_id'), 'exam_shares', ['tenant_id'], schema='ris')
    op.create_index('uq_ris_exam_preps_study', 'exam_preps', ['tenant_id', 'study_id'], unique=True, schema='ris')
    op.create_index('ix_ris_exam_attachments_study', 'exam_attachments', ['tenant_id', 'study_id'], schema='ris')
    op.create_index('ix_ris_exam_comments_study', 'exam_comments', ['tenant_id', 'study_id'], schema='ris')
    op.create_index('uq_ris_exam_comment_reads', 'exam_comment_reads', ['tenant_id', 'study_id', 'user_id'],
                    unique=True, schema='ris')
    op.create_index('ix_ris_exam_flags_study', 'exam_flags', ['tenant_id', 'study_id'], schema='ris')
    op.create_index('ix_ris_exam_shares_user', 'exam_shares', ['tenant_id', 'user_id'], schema='ris')
    app, service = f"{role_prefix}_app", f"{role_prefix}_service"
    for t in TENANT_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) "
                   f"WITH CHECK (tenant_id = {TENANT_EXPR})")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO {app}, {service}")
    # anexos e comentários não são apagados pela aplicação (histórico)
    op.execute(f"REVOKE DELETE ON ris.exam_attachments, ris.exam_comments, ris.exam_flags FROM {app}")


def downgrade(role_prefix: str = "vyonix") -> None:
    for t in reversed(['exam_preps', 'exam_attachments', 'exam_comments', 'exam_comment_reads', 'exam_flags', 'exam_shares']):
        op.drop_table(t, schema='ris')
