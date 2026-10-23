import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.config import Settings
from app.news_collector import NewsCollector, NewsTag
from app.service import RagService

NOW = datetime(2026, 10, 23, 3, tzinfo=timezone.utc)
URL = "https://n.news.naver.com/mnews/article/001/0000000001"


class MemoryStore:
    def __init__(self):
        self.rows = {}
        self.started = None
        self.records = []
    @contextmanager
    def collection_lock(self):
        yield True
    def due(self, now, interval):
        return self.started is None or now >= self.started + timedelta(seconds=interval)
    def mark(self, started, status, details, finished=None):
        self.started = started
        self.records.append(status)
    def targets(self):
        return [{"corp_code": "00126478", "company_name": "삼성중공업"}]
    def existing(self, urls, version):
        return {url: self.rows[url]["title"] for url in urls if url in self.rows}
    def save(self, rows):
        for row in rows:
            self.rows[row["url"]] = row
    def purge(self, cutoff):
        self.cutoff = cutoff
        return 0


class Embedding:
    async def embed(self, texts):
        return [[1.0] + [0.0] * 1535 for _ in texts]


def test_hourly_collection_classifies_before_storage_and_deduplicates(monkeypatch):
    store, calls = MemoryStore(), []
    monkeypatch.setattr("app.news_collector.NewsStore", lambda _: store)
    class Sources:
        async def news_headlines(self, company):
            calls.append(company)
            return {"items": [{"title": "기준금리 결정" if not company else "삼성중공업 수주 전망",
                "url": URL if not company else URL[:-1] + "2"}], "limitations": []}
    async def classifier(rows, targets):
        assert targets[0]["corp_code"] == "00126478"
        return [NewsTag(index=i, company_codes=["00126478"] if "삼성중공업" in row["title"] else [],
                        company_names=["삼성중공업"] if "삼성중공업" in row["title"] else [],
                        market_wide="금리" in row["title"], reason="모의 모델 분류") for i, row in enumerate(rows)]
    collector = NewsCollector(SimpleNamespace(store=object(), embedding=Embedding(), sources=Sources()),
                              None, Settings(), classifier)
    async def check():
        result = await collector.run_once(now=NOW)
        assert result["stored"] == 2 and calls == ["", "삼성중공업"]
        assert store.rows[URL]["market_wide"] and store.rows[URL[:-1] + "2"]["company_codes"] == ["00126478"]
        assert all("text" not in row for row in store.rows.values())
        assert store.cutoff == NOW - timedelta(days=30)
        assert (await collector.run_once(now=NOW + timedelta(minutes=59)))["status"] == "SKIPPED"
        result = await collector.run_once(now=NOW + timedelta(hours=1))
        assert result["stored"] == 0 and len(calls) == 4
    asyncio.run(check())


def test_news_article_read_rejects_future_and_keeps_failure_reason(monkeypatch):
    task_id, article_id = uuid4(), uuid4()
    class Store:
        def articles(self, identifiers, corp, company, as_of, days):
            assert corp == "00126478" and as_of == NOW
            return [{"id": str(article_id), "url": URL}]
    monkeypatch.setattr("app.service.NewsStore", lambda _: Store())
    class Sources:
        future = False
        async def get_context(self, task):
            return {"task_id": str(task_id), "organization_id": str(uuid4()), "corp_code": "00126478",
                    "company_name": "삼성중공업", "created_at": NOW.isoformat(), "disclosure_receipt_no": "20261015800457",
                    "memo": {"id": str(uuid4()), "version": 1, "content": "기존 메모"}}
        async def news_article(self, url):
            return {"url": url, "text": "기사 원문", "published_at": (NOW + timedelta(hours=1) if self.future else NOW - timedelta(hours=1)).isoformat(),
                    "modified_at": (NOW + timedelta(hours=1)).isoformat() if self.future == "modified" else None}
    async def check():
        sources = Sources()
        service = RagService(sources, Embedding(), object(), Settings())
        result = await service.read_market_news(task_id, [article_id])
        assert result["sources"][0]["quote"] == "기사 원문" and result["documents"][0]["url"] == URL
        sources.future = True
        rejected = await service.read_market_news(task_id, [article_id])
        assert not rejected["documents"] and rejected["limitations"]
        sources.future = "modified"
        assert not (await service.read_market_news(task_id, [article_id]))["documents"]
    asyncio.run(check())


def test_classification_failure_does_not_store_unclassified_rows(monkeypatch):
    store = MemoryStore()
    monkeypatch.setattr("app.news_collector.NewsStore", lambda _: store)
    class Sources:
        async def news_headlines(self, company):
            return {"items": [{"title": "확인이 필요한 제목", "url": URL}], "limitations": []}
    async def fail_classifier(rows, targets):
        raise ValueError("classification unavailable")
    collector = NewsCollector(SimpleNamespace(store=object(), embedding=Embedding(), sources=Sources()),
                              None, Settings(), fail_classifier)
    result = asyncio.run(collector.run_once(now=NOW))
    assert result["status"] == "FAILED" and not store.rows
