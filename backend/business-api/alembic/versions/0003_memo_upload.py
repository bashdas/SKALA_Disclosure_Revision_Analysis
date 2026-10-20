"""Allow unknown memo company and preserve uploaded file metadata.

Revision ID: 0003_memo_upload
Revises: 0002_align_report_flow
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_memo_upload"
down_revision = "0002_align_report_flow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("memos", "company_name", existing_type=sa.String(255), nullable=True, schema="core")
    op.add_column("memo_versions", sa.Column("original_filename", sa.String(255), nullable=True), schema="core")
    op.add_column("memo_versions", sa.Column("content_type", sa.String(255), nullable=True), schema="core")
    op.add_column("memo_versions", sa.Column("size_bytes", sa.BigInteger(), nullable=True), schema="core")
    op.add_column("memo_versions", sa.Column("content_hash", sa.String(64), nullable=True), schema="core")
    op.create_check_constraint("ck_memo_versions_size_nonnegative", "memo_versions", "size_bytes >= 0", schema="core")


def downgrade() -> None:
    # Never invent a company name or silently discard the provenance of an uploaded memo.
    op.execute(sa.text("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM core.memos WHERE company_name IS NULL)
               OR EXISTS (SELECT 1 FROM core.memo_versions WHERE original_filename IS NOT NULL
                          OR content_type IS NOT NULL OR size_bytes IS NOT NULL OR content_hash IS NOT NULL)
            THEN RAISE EXCEPTION 'Archive upload metadata and reconcile null companies before downgrading';
            END IF;
        END $$
    """))
    op.drop_constraint("ck_memo_versions_size_nonnegative", "memo_versions", type_="check", schema="core")
    for name in ("content_hash", "size_bytes", "content_type", "original_filename"):
        op.drop_column("memo_versions", name, schema="core")
    op.alter_column("memos", "company_name", existing_type=sa.String(255), nullable=False, schema="core")
