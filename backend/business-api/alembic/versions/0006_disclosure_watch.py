"""공시 등록 상태와 사용자별 관심 기업을 저장합니다."""
from alembic import op
import sqlalchemy as sa

revision = "0006_disclosure_watch"
down_revision = "0005_user_token_version"
branch_labels = None
depends_on = None


def upgrade():
    for column in (
        sa.Column("corp_code", sa.String(8), nullable=True),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("is_correction", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_registered", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("origin_receipt_no", sa.String(64), nullable=True),
    ):
        op.add_column("filings", column, schema="core")
    op.create_table("company_favorites",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("core.users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("corp_code", sa.String(8), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("stock_code", sa.String(6), nullable=False, server_default=""),
        sa.UniqueConstraint("user_id", "corp_code", name="uq_company_favorites_user_corp"), schema="core")


def downgrade():
    # 관심 기업이나 등록 상태를 잃는 되돌리기는 자료가 남아 있으면 중단합니다.
    op.execute(sa.text("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM core.company_favorites) OR EXISTS (
            SELECT 1 FROM core.filings WHERE corp_code IS NOT NULL OR NOT is_registered)
        THEN RAISE EXCEPTION 'Preserve watched company and filing state before downgrade'; END IF;
    END $$;"""))
    op.drop_table("company_favorites", schema="core")
    for name in ("origin_receipt_no", "is_registered", "is_correction", "title", "corp_code"):
        op.drop_column("filings", name, schema="core")
