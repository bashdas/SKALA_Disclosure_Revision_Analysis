"""시황 뉴스 관점을 허용합니다."""
import sqlalchemy as sa
from alembic import op

revision = "0010_market_news_perspective"
down_revision = "0009_user_settings"
branch_labels = None
depends_on = None


def replace(values):
    op.drop_constraint("ck_analysis_perspective_tasks_type", "analysis_perspective_tasks", schema="core", type_="check")
    op.create_check_constraint("ck_analysis_perspective_tasks_type", "analysis_perspective_tasks",
        "perspective_type IN (" + ",".join("'" + value + "'" for value in values) + ")", schema="core")


def upgrade():
    replace(["FINANCE", "FX_HEDGE", "INDUSTRY_CONTRACT", "MARKET_NEWS"])


def downgrade():
    op.execute(sa.text("DO $$ BEGIN IF EXISTS (SELECT 1 FROM core.analysis_perspective_tasks WHERE perspective_type='MARKET_NEWS') THEN RAISE EXCEPTION 'Archive market news perspectives before downgrade'; END IF; END $$"))
    replace(["FINANCE", "FX_HEDGE", "INDUSTRY_CONTRACT"])
