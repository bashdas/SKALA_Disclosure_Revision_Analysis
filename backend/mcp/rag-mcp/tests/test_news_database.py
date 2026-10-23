import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.config import Settings
from app.database import RagStore
from app.news_store import NewsStore
from sqlalchemy import text


def test_news_pending_classification_scope_cleanup_and_schedule(monkeypatch):
    url = os.environ.get("NEWS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Requires isolated NEWS_TEST_DATABASE_URL")
    assert "validation" in url.rsplit("/", 1)[-1], "전용 검증 DB에서만 실행합니다."
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
    store = RagStore(url)
    news = NewsStore(store)
    now = datetime.now(timezone.utc)
    cfg = Settings(news_usage_authorization="SYNTHETIC_TEST_ONLY")
    def row(n, age=1):
        return {"title": f"합성 뉴스 {n}", "original_title": f"<b>합성 뉴스 {n}</b>",
                "url": f"https://publisher.example/{n}", "original_url": f"https://publisher.example/{n}",
                "published_at": now - timedelta(days=age)}
    def tag(scope, codes=None, industry=None, high=False):
        return {"scope": scope, "company_codes": codes or [], "company_names": [], "market_wide": scope == "MACRO",
                "classification_reason": "합성 판단", "industry_tags": industry or [], "topic_tags": ["ENERGY"],
                "uncertainty": "본문 미수집", "confidence": 0.8, "importance": "HIGH" if high else "NORMAL"}
    try:
        news.save_pending([row(i) for i in range(6)], "합성 검색", now, 48)
        news.save_pending([row(0)], "추가 검색", now + timedelta(minutes=1), 48)
        pending = news.pending(now, 3, 20, "p1")
        assert len(pending) == 6
        first = next(r for r in pending if r["url"].endswith("/0"))
        assert len(first["search_queries"]) == 2 and first["classification_status"] == "PENDING"
        tags = [tag("COMPANY", ["00126478"]), tag("MACRO"), tag("INDUSTRY", industry=["조선"]),
                tag("COMPANY", ["00999999"]), tag("UNRESOLVED"), tag("MACRO", high=True)]
        for item in pending:
            number = int(item["url"].rsplit("/", 1)[1])
            news.classified(item, tags[number], "AI", "synthetic-model", "p1", now, cfg)
        found = news.search("00126478", "합성기업", now + timedelta(minutes=2), 7, None, 20,
                            "합성 뉴스", industries=["조선"], now=now)
        assert {int(r["url"].rsplit("/",1)[1]) for r in found} == {0, 1, 2, 5}
        assert all(r["title_only"] for r in found)
        assert len(news.search("00126478", "합성기업", now + timedelta(minutes=2), 7, None, 20,
                               scopes=["INDUSTRY"], industries=["조선"], now=now)) == 1
        assert not news.search("00126478", "합성기업", now - timedelta(minutes=1), 7, None, 20, now=now)
        news.save_pending([row(0)], "합성 검색", now + timedelta(days=1), 48)
        with store.engine.connect() as conn:
            current = conn.execute(text("SELECT expires_at,first_seen_at,last_seen_at FROM rag.market_news WHERE url='https://publisher.example/0'")).mappings().one()
            assert current["first_seen_at"] == now and current["expires_at"] == now + timedelta(days=6)
            assert current["last_seen_at"] == now + timedelta(days=1)
            assert "body" not in conn.execute(text("SELECT * FROM rag.market_news LIMIT 1")).keys()
        # 보고서에 복사한 제목 스냅샷은 활성 목록 삭제와 독립적입니다.
        snapshot = found[0].copy()
        preview = news.cleanup(now + timedelta(days=40), cfg)
        assert preview["delete_count"] == 6 and preview["dry_run"]
        with store.engine.connect() as conn:
            assert conn.scalar(text("SELECT count(*) FROM rag.market_news")) == 6
        capacity = cfg.model_copy(update={"news_max_articles": 2})
        assert news.cleanup(now, capacity)["delete_count"] == 4
        tiny = cfg.model_copy(update={"news_max_storage_bytes": 1})
        assert news.cleanup(now, tiny)["delete_count"] == 6
        news.cleanup(now, capacity, False)
        with store.engine.connect() as conn:
            assert conn.scalar(text("SELECT count(*) FROM rag.market_news")) == 2
            assert conn.scalar(text("SELECT count(*) FROM rag.market_news WHERE importance='HIGH'")) == 1
        news.cleanup(now + timedelta(days=40), cfg, False)
        assert snapshot["title"] and snapshot["url"]
        news.save_pending([row(6), row(7)], "이전 형식 검사", now, 48)
        with store.engine.begin() as conn:
            conn.execute(text("UPDATE rag.market_news SET classification_status='LEGACY' WHERE url='https://publisher.example/6'"))
            conn.execute(text("UPDATE rag.market_news SET published_at=NULL WHERE url='https://publisher.example/7'"))
        assert not news.pending(now, 3, 20, "new-policy", True)
        news.mark(now, "COMPLETED", {"calls": 1}, now)
        assert not news.due(now + timedelta(minutes=59), 3600)
        assert news.due(now + timedelta(hours=1), 3600)
        with news.collection_lock() as first_lock:
            reopened = NewsStore(RagStore(url))
            try:
                with reopened.collection_lock() as second_lock:
                    assert first_lock and not second_lock
            finally:
                reopened.engine.dispose()
        assert news.claim_api_call(now.date().isoformat(), 1)
        assert not news.claim_api_call(now.date().isoformat(), 1)
    finally:
        with store.engine.begin() as conn:
            conn.execute(text("TRUNCATE rag.market_news,rag.market_news_collection,rag.market_news_queries,rag.market_news_runs,rag.market_news_usage"))
        store.engine.dispose()
