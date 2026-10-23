"""제목 뉴스의 최소 적재와 분류 상태 및 만료 정책을 추가합니다."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0003_news_pipeline"
down_revision = "0002_market_news"
branch_labels = None
depends_on = None


def upgrade():
    columns = [
        sa.Column("original_title", sa.Text(), nullable=False, server_default=""),
        sa.Column("original_url", sa.Text()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("classification_status", sa.Text(), nullable=False, server_default="LEGACY"),
        sa.Column("classification_method", sa.Text(), nullable=False, server_default="legacy"),
        sa.Column("policy_version", sa.Text(), nullable=False, server_default="legacy"),
        sa.Column("scope", sa.Text(), nullable=False, server_default="UNRESOLVED"),
        sa.Column("industry_tags", pg.JSONB(), nullable=False, server_default="[]"),
        sa.Column("topic_tags", pg.JSONB(), nullable=False, server_default="[]"),
        sa.Column("search_queries", pg.JSONB(), nullable=False, server_default="[]"),
        sa.Column("uncertainty", sa.Text(), nullable=False, server_default=""),
        sa.Column("confidence", sa.Float()),
        sa.Column("importance", sa.Text(), nullable=False, server_default="NORMAL"),
        sa.Column("index_status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text()),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
    ]
    for column in columns:
        op.add_column("market_news", column, schema="rag")
    op.execute("UPDATE rag.market_news SET original_title=title, last_seen_at=first_seen_at, "
               "expires_at=first_seen_at+interval '48 hours'")
    op.alter_column("market_news", "expires_at", nullable=False, schema="rag")
    op.alter_column("market_news", "embedding", nullable=True, schema="rag")
    op.create_index("ix_market_news_scope_published", "market_news", ["scope", "published_at"], schema="rag")
    op.create_index("ix_market_news_industries", "market_news", ["industry_tags"], postgresql_using="gin", schema="rag")
    op.create_index("ix_market_news_expiry", "market_news", ["expires_at"], schema="rag")
    op.create_index("ix_market_news_processing", "market_news", ["classification_status", "next_retry_at"], schema="rag")
    op.create_index("ix_market_news_topics", "market_news", ["topic_tags"], postgresql_using="gin", schema="rag")
    op.create_check_constraint("ck_news_classification", "market_news", "classification_status IN ('LEGACY','PENDING','CLASSIFIED','UNRESOLVED','FAILED')", schema="rag")
    op.create_check_constraint("ck_news_scope", "market_news", "scope IN ('COMPANY','INDUSTRY','MACRO','UNRESOLVED')", schema="rag")
    op.create_table("market_news_queries", sa.Column("query", sa.Text(), primary_key=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", pg.JSONB(), nullable=False), schema="rag")
    op.create_table("market_news_runs", sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text(), nullable=False), sa.Column("details", pg.JSONB(), nullable=False), schema="rag")
    op.create_index("ix_market_news_runs_started", "market_news_runs", ["started_at"], schema="rag")
    op.create_table("market_news_usage", sa.Column("day", sa.Text(), primary_key=True),
        sa.Column("calls", sa.Integer(), nullable=False), schema="rag")


def downgrade():
    raise RuntimeError("뉴스 상태와 수집 이력의 데이터 손실을 막기 위해 자동 하향을 지원하지 않습니다.")
