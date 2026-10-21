"""Invalidate existing sessions after an authenticated password change."""
from alembic import op
import sqlalchemy as sa

revision = "0005_user_token_version"
down_revision = "0004_analysis_company"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default=sa.text("0")), schema="core")
    op.create_check_constraint("ck_users_token_version_nonnegative", "users", "token_version >= 0", schema="core")


def downgrade():
    # Downgrading removes persisted revocation state; do not make old JWTs valid again.
    op.execute(sa.text("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM core.users WHERE token_version > 0)
            THEN RAISE EXCEPTION 'Rotate JWT signing key and reconcile token versions before downgrade';
            END IF;
        END $$
    """))
    op.drop_constraint("ck_users_token_version_nonnegative", "users", schema="core", type_="check")
    op.drop_column("users", "token_version", schema="core")
