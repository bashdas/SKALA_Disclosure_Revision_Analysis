"""initial_core_schema

Revision ID: 0001_initial_core
Revises:
Create Date: 2026-10-20 15:15:19.804295
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0001_initial_core'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA core")
    op.create_table('organizations',
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='core'
    )
    op.create_table('filings',
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('company_name', sa.String(length=255), nullable=False),
    sa.Column('receipt_no', sa.String(length=64), nullable=False),
    sa.Column('filing_type', sa.String(length=100), nullable=False),
    sa.Column('filed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['core.organizations.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'receipt_no', name='uq_filings_organization_receipt'),
    schema='core'
    )
    op.create_index('ix_filings_receipt_no', 'filings', ['receipt_no'], unique=False, schema='core')
    op.create_table('memos',
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('company_name', sa.String(length=255), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('current_version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('current_version >= 1', name='ck_memos_current_version_positive'),
    sa.ForeignKeyConstraint(['organization_id'], ['core.organizations.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    schema='core'
    )
    op.create_index(op.f('ix_core_memos_organization_id'), 'memos', ['organization_id'], unique=False, schema='core')
    op.create_table('users',
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.Enum('RA', 'ANALYST', name='ck_users_role', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['core.organizations.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email', name='uq_users_email'),
    schema='core'
    )
    op.create_index('ix_users_organization_id', 'users', ['organization_id'], unique=False, schema='core')
    op.create_table('analysis_tasks',
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('requested_by', sa.Uuid(), nullable=False),
    sa.Column('filing_id', sa.Uuid(), nullable=False),
    sa.Column('memo_id', sa.Uuid(), nullable=False),
    sa.Column('base_memo_version', sa.Integer(), nullable=False),
    sa.Column('thread_id', sa.String(length=255), nullable=False),
    sa.Column('status', sa.Enum('CREATED', 'QUEUED', 'RUNNING', 'WAITING_CONTRACT_CONFIRMATION', 'WAITING_APPROVAL', 'RESUME_QUEUED', 'COMPLETED', 'FAILED', 'CANCELLED', name='ck_analysis_tasks_status', native_enum=False, create_constraint=True), server_default='CREATED', nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_code', sa.String(length=100), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('base_memo_version >= 1', name='ck_analysis_tasks_base_version_positive'),
    sa.ForeignKeyConstraint(['filing_id'], ['core.filings.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['memo_id'], ['core.memos.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['organization_id'], ['core.organizations.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['requested_by'], ['core.users.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('thread_id', name='uq_analysis_tasks_thread_id'),
    schema='core'
    )
    op.create_index('ix_analysis_tasks_organization_status', 'analysis_tasks', ['organization_id', 'status'], unique=False, schema='core')
    op.create_index('ix_analysis_tasks_status', 'analysis_tasks', ['status'], unique=False, schema='core')
    op.create_index(op.f('ix_core_analysis_tasks_filing_id'), 'analysis_tasks', ['filing_id'], unique=False, schema='core')
    op.create_index(op.f('ix_core_analysis_tasks_memo_id'), 'analysis_tasks', ['memo_id'], unique=False, schema='core')
    op.create_table('audit_logs',
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('action', sa.String(length=100), nullable=False),
    sa.Column('resource_type', sa.String(length=100), nullable=False),
    sa.Column('resource_id', sa.String(length=255), nullable=False),
    sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['core.organizations.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['core.users.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    schema='core'
    )
    op.create_index('ix_audit_logs_organization_created', 'audit_logs', ['organization_id', 'created_at'], unique=False, schema='core')
    op.create_table('contracts',
    sa.Column('filing_id', sa.Uuid(), nullable=False),
    sa.Column('contract_name', sa.String(length=255), nullable=False),
    sa.Column('counterparty', sa.String(length=255), nullable=True),
    sa.Column('amount', sa.Numeric(precision=24, scale=4), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['filing_id'], ['core.filings.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    schema='core'
    )
    op.create_index(op.f('ix_core_contracts_filing_id'), 'contracts', ['filing_id'], unique=False, schema='core')
    op.create_table('filing_versions',
    sa.Column('filing_id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('raw_content', sa.Text(), nullable=False),
    sa.Column('content_hash', sa.String(length=128), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('version >= 1', name='ck_filing_versions_version_positive'),
    sa.ForeignKeyConstraint(['filing_id'], ['core.filings.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('filing_id', 'version', name='uq_filing_versions_filing_version'),
    schema='core'
    )
    op.create_table('memo_versions',
    sa.Column('memo_id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('version >= 1', name='ck_memo_versions_version_positive'),
    sa.ForeignKeyConstraint(['created_by'], ['core.users.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['memo_id'], ['core.memos.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('memo_id', 'version', name='uq_memo_versions_memo_version'),
    schema='core'
    )
    op.create_table('analysis_events',
    sa.Column('analysis_task_id', sa.Uuid(), nullable=False),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('event_type', sa.String(length=100), nullable=False),
    sa.Column('payload_json', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('sequence >= 1', name='ck_analysis_events_sequence_positive'),
    sa.ForeignKeyConstraint(['analysis_task_id'], ['core.analysis_tasks.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('analysis_task_id', 'sequence', name='uq_analysis_events_task_sequence'),
    schema='core'
    )
    op.create_table('approvals',
    sa.Column('analysis_task_id', sa.Uuid(), nullable=False),
    sa.Column('approved_by', sa.Uuid(), nullable=True),
    sa.Column('status', sa.Enum('PENDING', 'APPROVED', 'PARTIALLY_APPROVED', 'REJECTED', name='ck_approvals_status', native_enum=False, create_constraint=True), server_default='PENDING', nullable=False),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['analysis_task_id'], ['core.analysis_tasks.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['approved_by'], ['core.users.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('analysis_task_id', name='uq_approvals_analysis_task_id'),
    schema='core'
    )
    op.create_table('revision_proposals',
    sa.Column('analysis_task_id', sa.Uuid(), nullable=False),
    sa.Column('claim_id', sa.String(length=255), nullable=False),
    sa.Column('impact_type', sa.Enum('FACT_UPDATE', 'CALCULATION_UPDATE', 'INTERPRETATION_REVIEW', 'NO_IMPACT', 'HOLD', name='ck_revision_proposals_impact_type', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('before_text', sa.Text(), nullable=False),
    sa.Column('after_text', sa.Text(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('evidence_json', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('validation_status', sa.Enum('PENDING', 'VALID', 'INVALID', name='ck_revision_proposals_validation_status', native_enum=False, create_constraint=True), server_default='PENDING', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['analysis_task_id'], ['core.analysis_tasks.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    schema='core'
    )
    op.create_index(op.f('ix_core_revision_proposals_analysis_task_id'), 'revision_proposals', ['analysis_task_id'], unique=False, schema='core')
    op.create_table('approval_items',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('approval_id', sa.Uuid(), nullable=False),
    sa.Column('revision_proposal_id', sa.Uuid(), nullable=False),
    sa.Column('approved', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['approval_id'], ['core.approvals.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['revision_proposal_id'], ['core.revision_proposals.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('approval_id', 'revision_proposal_id', name='uq_approval_items_approval_proposal'),
    schema='core'
    )
    op.create_table('revision_applications',
    sa.Column('analysis_task_id', sa.Uuid(), nullable=False),
    sa.Column('approval_id', sa.Uuid(), nullable=False),
    sa.Column('revision_proposal_id', sa.Uuid(), nullable=False),
    sa.Column('result_memo_version', sa.Integer(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('result_memo_version >= 1', name='ck_revision_applications_result_version_positive'),
    sa.ForeignKeyConstraint(['analysis_task_id'], ['core.analysis_tasks.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['approval_id'], ['core.approvals.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['revision_proposal_id'], ['core.revision_proposals.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('revision_proposal_id', name='uq_revision_applications_proposal'),
    schema='core'
    )
    op.create_index('ix_revision_applications_analysis_task_id', 'revision_applications', ['analysis_task_id'], unique=False, schema='core')


def downgrade() -> None:
    op.drop_index('ix_revision_applications_analysis_task_id', table_name='revision_applications', schema='core')
    op.drop_table('revision_applications', schema='core')
    op.drop_table('approval_items', schema='core')
    op.drop_index(op.f('ix_core_revision_proposals_analysis_task_id'), table_name='revision_proposals', schema='core')
    op.drop_table('revision_proposals', schema='core')
    op.drop_table('approvals', schema='core')
    op.drop_table('analysis_events', schema='core')
    op.drop_table('memo_versions', schema='core')
    op.drop_table('filing_versions', schema='core')
    op.drop_index(op.f('ix_core_contracts_filing_id'), table_name='contracts', schema='core')
    op.drop_table('contracts', schema='core')
    op.drop_index('ix_audit_logs_organization_created', table_name='audit_logs', schema='core')
    op.drop_table('audit_logs', schema='core')
    op.drop_index(op.f('ix_core_analysis_tasks_memo_id'), table_name='analysis_tasks', schema='core')
    op.drop_index(op.f('ix_core_analysis_tasks_filing_id'), table_name='analysis_tasks', schema='core')
    op.drop_index('ix_analysis_tasks_status', table_name='analysis_tasks', schema='core')
    op.drop_index('ix_analysis_tasks_organization_status', table_name='analysis_tasks', schema='core')
    op.drop_table('analysis_tasks', schema='core')
    op.drop_index('ix_users_organization_id', table_name='users', schema='core')
    op.drop_table('users', schema='core')
    op.drop_index(op.f('ix_core_memos_organization_id'), table_name='memos', schema='core')
    op.drop_table('memos', schema='core')
    op.drop_index('ix_filings_receipt_no', table_name='filings', schema='core')
    op.drop_table('filings', schema='core')
    op.drop_table('organizations', schema='core')
    op.execute("DROP SCHEMA core RESTRICT")
