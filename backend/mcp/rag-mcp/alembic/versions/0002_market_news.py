"""시황 뉴스 제목과 기업 태그 및 수집 상태를 저장합니다."""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql as pg

revision = "0002_market_news"
down_revision = "0001_rag_index"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("market_news",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("url", sa.Text(), nullable=False, unique=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("company_codes", pg.JSONB(), nullable=False),
        sa.Column("company_names", pg.JSONB(), nullable=False),
        sa.Column("market_wide", sa.Boolean(), nullable=False),
        sa.Column("classification_reason", sa.Text(), nullable=False),
        sa.Column("classifier_version", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("classified_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)), schema="rag")
    for name, cols, options in [
        ("published", ["published_at"], {}), ("first_seen", ["first_seen_at"], {}),
        ("codes", ["company_codes"], {"postgresql_using": "gin"}),
        ("names", ["company_names"], {"postgresql_using": "gin"}),
        ("common", ["market_wide", "first_seen_at"], {}),
    ]:
        op.create_index("ix_market_news_" + name, "market_news", cols, schema="rag", **options)
    op.create_table("market_news_collection",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("details", pg.JSONB(), nullable=False), schema="rag")


def downgrade():
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM rag.market_news) THEN RAISE EXCEPTION 'Archive market news before downgrade'; END IF; END $$")
    op.drop_table("market_news_collection", schema="rag")
    op.drop_table("market_news", schema="rag")
