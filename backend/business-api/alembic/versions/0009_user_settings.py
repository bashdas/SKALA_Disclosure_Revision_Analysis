"""계정 이름과 탈퇴 상태를 저장합니다."""
import sqlalchemy as sa
from alembic import op

revision = "0009_user_settings"
down_revision = "0008_sec_favorites"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("name", sa.String(100), nullable=False, server_default=""), schema="core")
    op.add_column("users", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()), schema="core")


def downgrade():
    op.drop_column("users", "is_active", schema="core")
    op.drop_column("users", "name", schema="core")
