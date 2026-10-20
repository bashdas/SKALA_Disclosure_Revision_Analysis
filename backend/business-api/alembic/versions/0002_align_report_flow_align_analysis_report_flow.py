"""align_analysis_report_flow

Revision ID: 0002_align_report_flow
Revises: 0001_initial_core
Create Date: 2026-10-20 15:47:23.086016
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0002_align_report_flow'
down_revision: Union[str, Sequence[str], None] = '0001_initial_core'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Frozen values: historical migrations must never depend on application Enum imports.
OLD_STATUSES = (
    "CREATED", "QUEUED", "RUNNING", "WAITING_CONTRACT_CONFIRMATION",
    "WAITING_APPROVAL", "RESUME_QUEUED", "COMPLETED", "FAILED", "CANCELLED",
)
NEW_STATUSES = (
    "CREATED", "QUEUED", "RUNNING", "SAVING", "COMPLETED",
    "COMPLETED_WITH_WARNINGS", "SAVE_FAILED", "FAILED", "CANCELLED",
)


def _guard(condition: str, message: str) -> None:
    # DO guards also survive offline SQL generation and run before destructive DDL.
    op.execute(sa.text(
        "DO $$ BEGIN IF " + condition + " THEN RAISE EXCEPTION '" + message + "'; END IF; END $$"
    ))


def _replace_status(values: tuple[str, ...]) -> None:
    op.drop_constraint("ck_analysis_tasks_status", "analysis_tasks", schema="core", type_="check")
    op.alter_column("analysis_tasks", "status", type_=sa.String(max(map(len, values))), schema="core")
    literals = ", ".join("'" + value + "'" for value in values)
    op.create_check_constraint("ck_analysis_tasks_status", "analysis_tasks", "status IN (" + literals + ")", schema="core")


def upgrade() -> None:
    _guard(
        "EXISTS (SELECT 1 FROM core.analysis_tasks WHERE status IN ('WAITING_CONTRACT_CONFIRMATION', 'WAITING_APPROVAL', 'RESUME_QUEUED'))",
        "Legacy analysis status requires manual reconciliation before upgrading",
    )
    op.add_column('analysis_tasks', sa.Column('disclosure_receipt_no', sa.String(64), nullable=True), schema='core')
    op.add_column('analysis_tasks', sa.Column('company_name_snapshot', sa.String(255), nullable=True), schema='core')
    op.execute(sa.text("""
        UPDATE core.analysis_tasks AS task
        SET disclosure_receipt_no = filing.receipt_no,
            company_name_snapshot = filing.company_name
        FROM core.filings AS filing WHERE task.filing_id = filing.id
    """))
    _guard(
        "EXISTS (SELECT 1 FROM core.analysis_tasks WHERE disclosure_receipt_no IS NULL OR company_name_snapshot IS NULL)",
        "Cannot backfill task receipt and company snapshot from filing",
    )
    op.alter_column('analysis_tasks', 'disclosure_receipt_no', nullable=False, schema='core')
    op.alter_column('analysis_tasks', 'company_name_snapshot', nullable=False, schema='core')
    op.add_column('analysis_tasks', sa.Column('corp_code', sa.String(8), nullable=True), schema='core')
    op.add_column('analysis_tasks', sa.Column('current_stage', sa.Enum('REQUEST_VALIDATION', 'INPUT_COLLECTION', 'RAG_PREPARATION', 'BASE_ANALYSIS', 'PERSPECTIVE_ANALYSIS', 'REPORT_GENERATION', 'REPORT_SAVE', name='ck_analysis_tasks_current_stage', native_enum=False, create_constraint=True), nullable=True), schema='core')
    op.add_column('analysis_tasks', sa.Column('has_warnings', sa.Boolean(), server_default=sa.text('false'), nullable=False), schema='core')
    op.add_column('analysis_tasks', sa.Column('error_stage', sa.Enum('REQUEST_VALIDATION', 'INPUT_COLLECTION', 'RAG_PREPARATION', 'BASE_ANALYSIS', 'PERSPECTIVE_ANALYSIS', 'REPORT_GENERATION', 'REPORT_SAVE', name='ck_analysis_tasks_error_stage', native_enum=False, create_constraint=True), nullable=True), schema='core')
    op.alter_column('analysis_tasks', 'filing_id', existing_type=sa.UUID(), nullable=True, schema='core')
    _replace_status(NEW_STATUSES)
    op.create_index('ix_analysis_tasks_duplicate_lookup', 'analysis_tasks', ['organization_id', 'memo_id', 'base_memo_version', 'disclosure_receipt_no', 'status'], unique=False, schema='core')
    op.create_index('ix_analysis_tasks_receipt_no', 'analysis_tasks', ['disclosure_receipt_no'], unique=False, schema='core')
    op.create_table('analysis_perspective_tasks',
    sa.Column('analysis_task_id', sa.Uuid(), nullable=False),
    sa.Column('perspective_type', sa.Enum('FINANCE', 'FX_HEDGE', 'INDUSTRY_CONTRACT', name='ck_analysis_perspective_tasks_type', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('selection_reason', sa.Text(), nullable=False),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('status', sa.Enum('REGISTERED', 'RUNNING', 'COMPLETED', 'INSUFFICIENT_EVIDENCE', 'LIMIT_REACHED', 'FAILED', name='ck_analysis_perspective_tasks_status', native_enum=False, create_constraint=True), server_default='REGISTERED', nullable=False),
    sa.Column('max_tool_calls', sa.Integer(), nullable=False),
    sa.Column('timeout_seconds', sa.Integer(), nullable=False),
    sa.Column('result_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('failure_code', sa.String(length=100), nullable=True),
    sa.Column('failure_message', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('max_tool_calls >= 0', name='ck_analysis_perspective_tasks_tool_limit'),
    sa.CheckConstraint('timeout_seconds > 0', name='ck_analysis_perspective_tasks_timeout'),
    sa.ForeignKeyConstraint(['analysis_task_id'], ['core.analysis_tasks.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('analysis_task_id', 'perspective_type', name='uq_analysis_perspective_tasks_task_type'),
    schema='core'
    )
    op.create_table('analysis_reports',
    sa.Column('analysis_task_id', sa.Uuid(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('report_json', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('has_warnings', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('no_additional_analysis_reason', sa.Text(), nullable=True),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('saved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['analysis_task_id'], ['core.analysis_tasks.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('analysis_task_id', name='uq_analysis_reports_analysis_task_id'),
    schema='core'
    )
    # Dependents must be dropped before approvals, even when tables contain data.
    op.drop_table('revision_applications', schema='core')
    op.drop_table('approval_items', schema='core')
    op.drop_table('approvals', schema='core')


def downgrade() -> None:
    # Restore schema only, never fabricate lost historical approval rows or task inputs.
    _guard(
        "EXISTS (SELECT 1 FROM core.analysis_reports) OR EXISTS (SELECT 1 FROM core.analysis_perspective_tasks)",
        "Archive and explicitly remove report and perspective data before downgrading",
    )
    _guard(
        "EXISTS (SELECT 1 FROM core.analysis_tasks WHERE filing_id IS NULL OR status IN ('SAVING', 'COMPLETED_WITH_WARNINGS', 'SAVE_FAILED'))",
        "Tasks incompatible with the old schema require manual reconciliation before downgrading",
    )
    op.drop_table('analysis_reports', schema='core')
    op.drop_table('analysis_perspective_tasks', schema='core')
    op.drop_index('ix_analysis_tasks_receipt_no', table_name='analysis_tasks', schema='core')
    op.drop_index('ix_analysis_tasks_duplicate_lookup', table_name='analysis_tasks', schema='core')
    _replace_status(OLD_STATUSES)
    op.alter_column('analysis_tasks', 'filing_id', existing_type=sa.UUID(), nullable=False, schema='core')
    for column in ('error_stage', 'has_warnings', 'current_stage', 'company_name_snapshot', 'corp_code', 'disclosure_receipt_no'):
        op.drop_column('analysis_tasks', column, schema='core')
    op.create_table('approvals',
    sa.Column('analysis_task_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('approved_by', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('status', sa.VARCHAR(length=18), server_default=sa.text("'PENDING'::character varying"), autoincrement=False, nullable=False),
    sa.Column('approved_at', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=True),
    sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.CheckConstraint("status::text = ANY (ARRAY['PENDING'::character varying, 'APPROVED'::character varying, 'PARTIALLY_APPROVED'::character varying, 'REJECTED'::character varying]::text[])", name=op.f('ck_approvals_status')),
    sa.ForeignKeyConstraint(['analysis_task_id'], ['core.analysis_tasks.id'], name=op.f('approvals_analysis_task_id_fkey'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['approved_by'], ['core.users.id'], name=op.f('approvals_approved_by_fkey'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('approvals_pkey')),
    sa.UniqueConstraint('analysis_task_id', name=op.f('uq_approvals_analysis_task_id'), postgresql_include=[], postgresql_nulls_not_distinct=False),
    schema='core'
    )
    op.create_table('approval_items',
    sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('approval_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('revision_proposal_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('approved', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['approval_id'], ['core.approvals.id'], name=op.f('approval_items_approval_id_fkey'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['revision_proposal_id'], ['core.revision_proposals.id'], name=op.f('approval_items_revision_proposal_id_fkey'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('approval_items_pkey')),
    sa.UniqueConstraint('approval_id', 'revision_proposal_id', name=op.f('uq_approval_items_approval_proposal'), postgresql_include=[], postgresql_nulls_not_distinct=False),
    schema='core'
    )
    op.create_table('revision_applications',
    sa.Column('analysis_task_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('approval_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('revision_proposal_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('result_memo_version', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.CheckConstraint('result_memo_version >= 1', name=op.f('ck_revision_applications_result_version_positive')),
    sa.ForeignKeyConstraint(['analysis_task_id'], ['core.analysis_tasks.id'], name=op.f('revision_applications_analysis_task_id_fkey'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['approval_id'], ['core.approvals.id'], name=op.f('revision_applications_approval_id_fkey'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['revision_proposal_id'], ['core.revision_proposals.id'], name=op.f('revision_applications_revision_proposal_id_fkey'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('revision_applications_pkey')),
    sa.UniqueConstraint('revision_proposal_id', name=op.f('uq_revision_applications_proposal'), postgresql_include=[], postgresql_nulls_not_distinct=False),
    schema='core'
    )
    op.create_index(op.f('ix_revision_applications_analysis_task_id'), 'revision_applications', ['analysis_task_id'], unique=False, schema='core')
