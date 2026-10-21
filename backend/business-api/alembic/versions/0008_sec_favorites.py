"""SEC 기업 식별자를 관심 기업에 저장합니다."""
from alembic import op
import sqlalchemy as sa

revision = "0008_sec_favorites"
down_revision = "0007_memo_delete"
branch_labels = None
depends_on = None

def upgrade():
    op.alter_column("company_favorites", "corp_code", type_=sa.String(64), existing_type=sa.String(8), schema="core")

def downgrade():
    op.execute(sa.text("DO $$ BEGIN IF EXISTS (SELECT 1 FROM core.company_favorites WHERE length(corp_code)>8) THEN RAISE EXCEPTION 'Preserve SEC favorites before downgrade'; END IF; END $$;"))
    op.alter_column("company_favorites", "corp_code", type_=sa.String(8), existing_type=sa.String(64), schema="core")
