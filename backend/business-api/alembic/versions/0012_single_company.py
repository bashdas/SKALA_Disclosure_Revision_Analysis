"""Remove tenant partitioning for a single-company installation."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0012_single_company"
down_revision = "0011_internal_reports"
branch_labels = depends_on = None
TABLES = ("users", "filings", "memos", "analysis_tasks", "audit_logs", "internal_reports")
LEGACY_ID = "00000000-0000-0000-0000-000000000001"


def upgrade():
    # Never silently discard distinct legacy filing records and their references.
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT receipt_no FROM core.filings GROUP BY receipt_no HAVING count(*) > 1)
      THEN RAISE EXCEPTION 'Duplicate filing receipts across legacy organizations: reconcile before single-company migration';
      END IF;
    END $$""")
    for table in TABLES:
        op.drop_column(table, "organization_id", schema="core")
    op.drop_table("organizations", schema="core")
    op.create_unique_constraint("uq_filings_receipt", "filings", ["receipt_no"], schema="core")
    op.create_index("ix_analysis_tasks_duplicate_lookup", "analysis_tasks",
        ["memo_id", "base_memo_version", "disclosure_receipt_no", "status"], schema="core")
    op.create_index("ix_audit_logs_created", "audit_logs", ["created_at"], schema="core")
    # Invalidate already issued sessions; no token carries a tenant identity anymore.
    op.execute("UPDATE core.users SET token_version = token_version + 1")


def downgrade():
    # A downgraded installation has one shared legacy organization; old partitions cannot be recovered.
    op.create_table("organizations", sa.Column("id", UUID(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), schema="core")
    op.execute(sa.text("INSERT INTO core.organizations(id, name) VALUES (CAST(:id AS uuid), 'Single company')").bindparams(id=LEGACY_ID))
    op.drop_constraint("uq_filings_receipt", "filings", schema="core", type_="unique")
    op.drop_index("ix_analysis_tasks_duplicate_lookup", table_name="analysis_tasks", schema="core")
    op.drop_index("ix_audit_logs_created", table_name="audit_logs", schema="core")
    for table in TABLES:
        op.add_column(table, sa.Column("organization_id", UUID(), server_default=sa.text("'" + LEGACY_ID + "'::uuid"), nullable=False), schema="core")
        op.create_foreign_key(None, table, "organizations", ["organization_id"], ["id"],
            source_schema="core", referent_schema="core", ondelete="RESTRICT")
        op.alter_column(table, "organization_id", server_default=None, schema="core")
    op.create_unique_constraint("uq_filings_organization_receipt", "filings", ["organization_id", "receipt_no"], schema="core")
    op.create_index("ix_users_organization_id", "users", ["organization_id"], schema="core")
    op.create_index("ix_core_memos_organization_id", "memos", ["organization_id"], schema="core")
    op.create_index("ix_core_internal_reports_organization_id", "internal_reports", ["organization_id"], schema="core")
    op.create_index("ix_analysis_tasks_organization_status", "analysis_tasks", ["organization_id", "status"], schema="core")
    op.create_index("ix_analysis_tasks_duplicate_lookup", "analysis_tasks", ["organization_id", "memo_id", "base_memo_version", "disclosure_receipt_no", "status"], schema="core")
    op.create_index("ix_audit_logs_organization_created", "audit_logs", ["organization_id", "created_at"], schema="core")
