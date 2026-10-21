"""기존 분석 원문을 보존하며 메모를 목록에서 삭제합니다."""
from alembic import op
import sqlalchemy as sa
revision = "0007_memo_delete"
down_revision = "0006_disclosure_watch"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("memos", sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()), schema="core")

def downgrade():
    op.execute(sa.text("DO $$ BEGIN IF EXISTS (SELECT 1 FROM core.memos WHERE is_deleted) THEN RAISE EXCEPTION 'Preserve deleted memo state before downgrade'; END IF; END $$;"))
    op.drop_column("memos", "is_deleted", schema="core")
