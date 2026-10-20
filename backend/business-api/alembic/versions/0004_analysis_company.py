"""Allow analysis creation before OpenDART identifies the company."""
from alembic import op
import sqlalchemy as sa

revision = "0004_analysis_company"
down_revision = "0003_memo_upload"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("analysis_tasks", "company_name_snapshot", existing_type=sa.String(255), nullable=True, schema="core")


def downgrade() -> None:
    op.execute(sa.text("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM core.analysis_tasks WHERE company_name_snapshot IS NULL)
            THEN RAISE EXCEPTION 'Reconcile unknown analysis companies before downgrading';
            END IF;
        END $$
    """))
    op.alter_column("analysis_tasks", "company_name_snapshot", existing_type=sa.String(255), nullable=False, schema="core")
