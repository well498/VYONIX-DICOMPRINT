"""REPORT: texto rico (HTML seguro) em laudos, versões e modelos; modelos pessoais; frases rápidas; revisão
(segunda leitura) e histórico do rascunho. Aditiva: conteúdo existente continua como texto simples.

Revisão: report_0011
Anterior: report_0010
"""
from alembic import op
import sqlalchemy as sa


revision = 'report_0011'
down_revision = 'report_0010'
branch_labels = None
depends_on = None

TENANT_TABLES = ("report.phrases", "report.draft_revisions", "report.phrase_prefs")
TENANT_EXPR = "nullif(current_setting('vyonix.tenant_id', true), '')::uuid"


def _base():
    return [sa.Column('id', sa.Uuid(), nullable=False),
            sa.Column('tenant_id', sa.Uuid(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('row_version', sa.Integer(), nullable=False)]


def upgrade(role_prefix: str = "vyonix") -> None:
    op.add_column('reports', sa.Column('body_format', sa.String(8), nullable=False, server_default='text'),
                  schema='report')
    for c in (sa.Column('review_requested_by', sa.String(120), nullable=True),
              sa.Column('review_requested_at', sa.DateTime(timezone=True), nullable=True),
              sa.Column('reviewer_id', sa.Uuid(), nullable=True),
              sa.Column('review_note', sa.String(1000), nullable=True),
              sa.Column('draft_revision', sa.Integer(), nullable=False, server_default='0')):
        op.add_column('reports', c, schema='report')
    op.add_column('report_versions', sa.Column('body_format', sa.String(8), nullable=False, server_default='text'),
                  schema='report')
    op.add_column('report_versions', sa.Column('author', sa.String(120), nullable=True), schema='report')
    op.add_column('report_versions', sa.Column('reviewer', sa.String(160), nullable=True), schema='report')
    op.add_column('report_versions', sa.Column('changes', sa.JSON(), nullable=True), schema='report')
    op.add_column('template_versions', sa.Column('content_format', sa.String(8), nullable=False,
                                                 server_default='text'), schema='report')
    op.add_column('templates', sa.Column('owner_user_id', sa.Uuid(), nullable=True), schema='report')
    op.add_column('physicians', sa.Column('requires_review', sa.Boolean(), nullable=False,
                                          server_default=sa.text('false')), schema='report')
    op.create_table(
        'phrases',
        sa.Column('owner_user_id', sa.Uuid(), nullable=True),
        sa.Column('title', sa.String(120), nullable=False),
        sa.Column('shortcut', sa.String(30), nullable=True),
        sa.Column('modality', sa.String(16), nullable=True),
        sa.Column('category', sa.String(60), nullable=True),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_by', sa.String(120), nullable=False),
        *_base(),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_phrases')),
        schema='report')
    op.create_index(op.f('ix_phrases_tenant_id'), 'phrases', ['tenant_id'], schema='report')
    op.create_index('ix_report_phrases_owner', 'phrases', ['tenant_id', 'owner_user_id'], schema='report')
    op.create_table(
        'phrase_prefs',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('phrase_id', sa.Uuid(), sa.ForeignKey('report.phrases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('favorite', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('shortcut', sa.String(30), nullable=True),
        *_base(),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_phrase_prefs')),
        schema='report')
    op.create_index(op.f('ix_phrase_prefs_tenant_id'), 'phrase_prefs', ['tenant_id'], schema='report')
    op.create_index('uq_report_phrase_prefs', 'phrase_prefs', ['tenant_id', 'user_id', 'phrase_id'], unique=True,
                    schema='report')
    op.create_table(
        'draft_revisions',
        sa.Column('report_id', sa.Uuid(), sa.ForeignKey('report.reports.id'), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('body_format', sa.String(8), nullable=False),
        sa.Column('author', sa.String(120), nullable=False),
        sa.Column('event', sa.String(20), nullable=False),
        *_base(),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_draft_revisions')),
        schema='report')
    op.create_index(op.f('ix_draft_revisions_tenant_id'), 'draft_revisions', ['tenant_id'], schema='report')
    op.create_index('uq_report_draft_revisions', 'draft_revisions', ['tenant_id', 'report_id', 'revision'],
                    unique=True, schema='report')
    app, service = f"{role_prefix}_app", f"{role_prefix}_service"
    for t in TENANT_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) "
                   f"WITH CHECK (tenant_id = {TENANT_EXPR})")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO {app}, {service}")


def downgrade(role_prefix: str = "vyonix") -> None:
    op.drop_table('draft_revisions', schema='report')
    op.drop_table('phrase_prefs', schema='report')
    op.drop_table('phrases', schema='report')
    op.drop_column('physicians', 'requires_review', schema='report')
    op.drop_column('templates', 'owner_user_id', schema='report')
    op.drop_column('template_versions', 'content_format', schema='report')
    op.drop_column('report_versions', 'changes', schema='report')
    op.drop_column('report_versions', 'reviewer', schema='report')
    op.drop_column('report_versions', 'author', schema='report')
    op.drop_column('report_versions', 'body_format', schema='report')
    for c in ('draft_revision', 'review_note', 'reviewer_id', 'review_requested_at', 'review_requested_by',
              'body_format'):
        op.drop_column('reports', c, schema='report')
