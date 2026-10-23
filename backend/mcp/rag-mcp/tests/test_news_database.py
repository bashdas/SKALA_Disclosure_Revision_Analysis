import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.database import RagStore
from app.news_store import NewsStore
from sqlalchemy import text


def test_news_storage_scope_retention_and_restart_schedule(monkeypatch):
    url = os.environ.get("NEWS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Requires isolated NEWS_TEST_DATABASE_URL")
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
    store = RagStore(url)
    news = NewsStore(store)
    now = datetime(2026, 10, 23, 3, tzinfo=timezone.utc)
    vector = [1.0] + [0.0] * 1535
    def row(name, days, codes, common):
        return {"title": name, "url": "https://n.news.naver.com/mnews/article/001/" + str(1000000000 + days),
                "company_codes": codes, "company_names": [], "market_wide": common,
                "classification_reason": "모의 분류", "classifier_version": "test",
                "embedding": vector, "first_seen_at": now - timedelta(days=days), "classified_at": now}
    rows = [row("기업 뉴스", 1, ["00126478"], False), row("공통 시황", 2, [], True),
            row("다른 기업", 3, ["00999999"], False), row("오래된 기사", 31, [], True),
            row("미래 기사", -1, [], True)]
    try:
        news.save(rows)
        news.save(rows)
        found = news.search("00126478", "삼성중공업", now, 30, vector, 10)
        assert {r["title"] for r in found} == {"기업 뉴스", "공통 시황"}
        assert news.purge(now - timedelta(days=30)) == 1
        with store.engine.connect() as conn:
            assert conn.scalar(text("select count(*) from rag.market_news")) == 4
            assert "text" not in conn.execute(text("select * from rag.market_news limit 1")).keys()
        news.mark(now, "COMPLETED", {"stored": 4}, now)
        reopened = NewsStore(RagStore(url))
        try:
            assert not reopened.due(now + timedelta(minutes=59), 3600)
            assert reopened.due(now + timedelta(hours=1), 3600)
            with news.collection_lock() as first, reopened.collection_lock() as second:
                assert first and not second
        finally:
            reopened.engine.dispose()
    finally:
        with store.engine.begin() as conn:
            conn.execute(text("TRUNCATE rag.market_news, rag.market_news_collection"))
        store.engine.dispose()
