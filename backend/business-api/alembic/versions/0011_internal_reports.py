"""Versioned internal reference reports and analysis manifests."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "0011_internal_reports"
down_revision = "0010_market_news_perspective"
branch_labels = depends_on = None


def upgrade():
    op.create_table("internal_reports",
        sa.Column("id", UUID(), primary_key=True),
        sa.Column("organization_id", UUID(), sa.ForeignKey("core.organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("corp_code", sa.String(8), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("published_at", sa.Date(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), schema="core")
    for key in ("organization_id", "corp_code"):
        op.create_index("ix_core_internal_reports_" + key, "internal_reports", [key], schema="core")
    op.create_table("internal_report_versions",
        sa.Column("id", UUID(), primary_key=True),
        sa.Column("report_id", UUID(), sa.ForeignKey("core.internal_reports.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("corp_code", sa.String(8), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("published_at", sa.Date(), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("pages", JSONB(), nullable=False),
        sa.Column("pdf_data", sa.LargeBinary(), nullable=False),
        sa.Column("created_by", UUID(), sa.ForeignKey("core.users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("report_id", "version", name="uq_internal_report_version"), schema="core")
    op.create_table("analysis_report_references",
        sa.Column("task_id", UUID(), sa.ForeignKey("core.analysis_tasks.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("versions", JSONB(), nullable=False), schema="core")


def downgrade():
    for name in ("analysis_report_references", "internal_report_versions", "internal_reports"):
        op.drop_table(name, schema="core")
