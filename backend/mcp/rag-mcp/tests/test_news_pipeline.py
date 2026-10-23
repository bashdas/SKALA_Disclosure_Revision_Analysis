import asyncio
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
from app.config import Settings
from app.news_collector import (
    NewsCollector,
    NewsTag,
    clear_company_tag,
    mentions,
)
from app.service import RagService

NOW = datetime(2026, 10, 23, 3, tzinfo=timezone.utc)
TARGET = {
    "corp_code": "00126478",
    "company_name": "가상중공업",
    "aliases": ["가상"],
    "industries": ["조선"],
}


class MemoryStore:
    def __init__(self):
        self.rows, self.states, self.calls = {}, {}, 0
        self.started = None

    @contextmanager
    def collection_lock(self):
        yield True

    def due(self, now, interval):
        return self.started is None or now >= self.started + timedelta(seconds=interval)

    def mark(self, now, *args):
        self.started = now

    def targets(self):
        return [TARGET, TARGET]

    def query_states(self):
        return self.states

    def record_query(self, query, now, complete, details):
        self.states[query] = {
            "last_success_at": now if complete else None,
            "last_checked_at": now,
            "details": details,
        }

    def claim_api_call(self, day, budget):
        self.calls += 1
        return self.calls <= budget

    def save_pending(self, rows, query, now, hours):
        for row in rows:
            if row["url"] not in self.rows:
                self.rows[row["url"]] = {
                    **row,
                    "id": str(uuid4()),
                    "classification_status": "PENDING",
                    "search_queries": [query],
                    "attempts": 0,
                }

    def pending(self, now, attempts, limit, policy, retry):
        return [
            r.copy()
            for r in self.rows.values()
            if r["classification_status"] in {"PENDING", "FAILED"}
        ][:limit]

    def classified(self, item, tag, *args):
        self.rows[item["url"]].update(tag, classification_status="CLASSIFIED")

    def classification_failed(self, items, now, error):
        for item in items:
            self.rows[item["url"]].update(
                classification_status="FAILED", last_error=error
            )

    def cleanup(self, *args):
        return {"dry_run": False, "delete_count": 0}

    def run_record(self, *args):
        pass


def news_tag(i=0, scope="MACRO", codes=None):
    return NewsTag(
        index=i,
        company_codes=codes or [],
        scope=scope,
        industry_tags=[],
        topic_tags=["INTEREST_RATE"],
        confidence=0.8,
        uncertainty="합성 판단",
        importance="NORMAL",
        reason="합성 제목 판단입니다.",
    )


def test_exact_names_aliases_multiple_and_parent_ambiguity():
    assert mentions("가상중공업과 협력", "가상중공업")
    assert not mentions("가상중공업서비스 수주", "가상중공업")
    other = {
        "corp_code": "00222222",
        "company_name": "가상지주",
        "aliases": ["가상"],
        "industries": [],
    }
    assert clear_company_tag("가상중공업, 합성 수주 보도", [TARGET]).company_codes == [
        TARGET["corp_code"]
    ]
    assert clear_company_tag("가상, 사업 확대", [TARGET, other]) is None
    assert clear_company_tag("가상중공업과 가상지주 협력", [TARGET, other]) is None
    assert clear_company_tag("가상중공업서비스 수주", [TARGET]) is None
    assert clear_company_tag("기준금리 변동", [TARGET]) is None


def test_pending_survives_failure_retry_and_hourly_dedup(monkeypatch):
    store, calls = MemoryStore(), []
    monkeypatch.setattr("app.news_collector.NewsStore", lambda _: store)

    class Sources:
        async def news_search(self, query, start, display):
            calls.append(query)
            return {
                "items": [
                    {
                        "title": "합성 금리 결정",
                        "original_title": "합성 금리 결정",
                        "url": "https://publisher.example/1",
                        "published_at": (NOW - timedelta(hours=1)).isoformat(),
                    }
                ],
                "total": 1,
                "raw_count": 1,
            }

    fail = True

    async def classifier(rows, targets):
        assert len(targets) == 1 and store.rows
        assert all(
            r["classification_status"] in {"PENDING", "FAILED"}
            for r in store.rows.values()
        )
        if fail:
            raise ValueError("synthetic_failure")
        return [news_tag(i) for i, _ in enumerate(rows)]

    cfg = Settings(
        news_usage_authorization="SYNTHETIC_TEST_ONLY",
        news_topics=["기준금리"],
        news_classification_retries=0,
    )
    collector = NewsCollector(
        SimpleNamespace(store=object(), sources=Sources()), None, cfg, classifier
    )

    async def check():
        nonlocal fail
        result = await collector.run_once(now=NOW)
        assert result["status"] == "COMPLETED_WITH_WARNINGS" and len(store.rows) == 1
        assert next(iter(store.rows.values()))["classification_status"] == "FAILED"
        assert calls == ["기준금리", "가상중공업"]
        fail = False
        result = await collector.run_once(
            now=NOW + timedelta(minutes=1), force=True, retry_only=True
        )
        assert result["classified"] == 1 and len(calls) == 2
        assert not next(iter(store.rows.values()))["company_codes"]
        assert (await collector.run_once(now=NOW + timedelta(minutes=59)))[
            "status"
        ] == "SKIPPED"
        await collector.run_once(now=NOW + timedelta(hours=2))
        assert len(store.rows) == 1

    asyncio.run(check())


def test_no_permission_has_no_collection_or_ai(monkeypatch):
    monkeypatch.setattr("app.news_collector.NewsStore", lambda _: MemoryStore())
    collector = NewsCollector(SimpleNamespace(store=object()), None, Settings())
    assert asyncio.run(collector.run_once())["status"] == "BLOCKED"


def test_page_and_company_budgets_preserve_common_quota(monkeypatch):
    store = MemoryStore()
    monkeypatch.setattr("app.news_collector.NewsStore", lambda _: store)

    class Sources:
        async def news_search(self, query, start, display):
            return {"items": [], "total": 1000, "raw_count": 100}

    cfg = Settings(
        news_usage_authorization="SYNTHETIC_TEST_ONLY",
        news_topics=["기준금리"],
        news_max_pages=1,
        news_company_call_budget=1,
        news_macro_call_budget=1,
    )
    result = asyncio.run(
        NewsCollector(
            SimpleNamespace(store=object(), sources=Sources()), None, cfg
        ).run_once(now=NOW)
    )
    assert result["calls"] == 2 and "PAGE_LIMIT_REACHED" in result["errors"]
    assert all(state["last_success_at"] is None for state in store.states.values())


def test_rag_server_scope_title_only_cutoff_and_policy(monkeypatch):
    task_id, article_id = uuid4(), uuid4()
    captured = []
    row = {
        "id": str(article_id),
        "title": "합성 금리 보도",
        "published_at": (NOW - timedelta(hours=1)).isoformat(),
        "url": "https://publisher.example/1",
        "first_seen_at": (NOW - timedelta(minutes=1)).isoformat(),
        "scope": "MACRO",
    }

    class Store:
        def search(self, *args):
            captured.append(args)
            return [row]

        def articles(self, *args):
            return [row]

        def status(self):
            return {
                "status": "COMPLETED",
                "finished_at": NOW.isoformat(),
                "details": {"queries": ["secret-user-query"]},
            }

    monkeypatch.setattr("app.service.NewsStore", lambda _: Store())

    class Sources:
        async def get_context(self, task):
            return {
                "task_id": str(task_id),
                "organization_id": str(uuid4()),
                "corp_code": TARGET["corp_code"],
                "company_name": TARGET["company_name"],
                "created_at": NOW.isoformat(),
                "disclosure_receipt_no": "20261015800457",
                "memo": {"id": str(uuid4()), "version": 1, "content": "합성 메모"},
            }

    async def check():
        cfg = Settings(
            news_usage_authorization="SYNTHETIC_TEST_ONLY",
            news_company_industries={TARGET["corp_code"]: ["조선"]},
        )
        service = RagService(Sources(), None, object(), cfg)
        result = await service.search_market_news(
            task_id, "금리", as_of="2026-10-22", days=3
        )
        assert result["mode"] == "HISTORICAL" and result["title_only"]
        assert (
            result["sources"][0]["quote"] == row["title"]
            and result["sources"][0]["location"] == "news:title"
        )
        assert captured[0][0] == TARGET["corp_code"] and captured[0][-1] == ["조선"]
        assert "secret-user-query" not in str(result)
        stored = await service.read_market_news(task_id, [article_id])
        assert stored["documents"][0]["text"] == row["title"]
        blocked = await RagService(
            Sources(), None, object(), Settings()
        ).search_market_news(task_id, "금리")
        assert (
            blocked["error"] == "NEWS_USAGE_NOT_AUTHORIZED" and not blocked["documents"]
        )

    asyncio.run(check())


def test_unknown_codes_fail_and_short_alias_is_unresolved(monkeypatch):
    store = MemoryStore()
    monkeypatch.setattr("app.news_collector.NewsStore", lambda _: store)
    store.rows["https://publisher.example/ambiguous"] = {
        "id": str(uuid4()),
        "title": "가상, 투자 검토",
        "url": "https://publisher.example/ambiguous",
        "classification_status": "PENDING",
        "search_queries": [],
        "attempts": 0,
    }

    async def classifier(rows, targets):
        return [news_tag(scope="COMPANY", codes=[TARGET["corp_code"]])]

    cfg = Settings(news_usage_authorization="SYNTHETIC_TEST_ONLY")
    collector = NewsCollector(SimpleNamespace(store=object()), None, cfg, classifier)
    asyncio.run(collector.process_pending([TARGET], NOW))
    assert store.rows["https://publisher.example/ambiguous"]["scope"] == "UNRESOLVED"
    assert not store.rows["https://publisher.example/ambiguous"]["company_codes"]
    store.rows["https://publisher.example/ambiguous"]["classification_status"] = (
        "PENDING"
    )

    async def unknown(rows, targets):
        return [news_tag(scope="COMPANY", codes=["99999999"])]

    collector.classifier = unknown
    asyncio.run(collector.process_pending([TARGET], NOW))
    assert (
        store.rows["https://publisher.example/ambiguous"]["classification_status"]
        == "FAILED"
    )


def test_classification_budget_leaves_pending_and_future_titles_excluded(monkeypatch):
    store = MemoryStore()
    monkeypatch.setattr("app.news_collector.NewsStore", lambda _: store)

    class Sources:
        async def news_search(self, query, start, display):
            return {
                "items": [
                    {
                        "title": "미래 합성 뉴스",
                        "original_title": "미래 합성 뉴스",
                        "url": "https://publisher.example/future",
                        "published_at": (NOW + timedelta(hours=1)).isoformat(),
                    }
                ],
                "total": 1,
                "raw_count": 1,
            }

    cfg = Settings(
        news_usage_authorization="SYNTHETIC_TEST_ONLY",
        news_topics=["기준금리"],
        news_classification_token_budget=1000,
    )
    collector = NewsCollector(
        SimpleNamespace(store=object(), sources=Sources()), None, cfg
    )
    asyncio.run(collector.run_once(now=NOW))
    assert not store.rows
    store.rows["https://publisher.example/pending"] = {
        "id": str(uuid4()),
        "title": "합성 금리 뉴스",
        "url": "https://publisher.example/pending",
        "classification_status": "PENDING",
        "search_queries": [],
        "attempts": 0,
    }
    result = asyncio.run(collector.process_pending([TARGET], NOW))
    assert result["errors"] == ["CLASSIFICATION_BUDGET_EXHAUSTED"]
    assert (
        store.rows["https://publisher.example/pending"]["classification_status"]
        == "PENDING"
    )


def test_inconsistent_tag_does_not_fail_other_articles_in_batch(monkeypatch):
    store = MemoryStore()
    monkeypatch.setattr("app.news_collector.NewsStore", lambda _: store)
    for i in range(3):
        url = f"https://publisher.example/batch/{i}"
        store.rows[url] = {"id": str(uuid4()), "title": f"합성 시황 제목 {i}", "url": url,
                           "classification_status": "PENDING", "search_queries": [], "attempts": 0}
    async def classifier(rows, targets):
        return [news_tag(0), news_tag(1, "MACRO", [TARGET["corp_code"]]), news_tag(2, "INDUSTRY")]
    cfg = Settings(news_usage_authorization="SYNTHETIC_TEST_ONLY")
    collector = NewsCollector(SimpleNamespace(store=object()), None, cfg, classifier)
    result = asyncio.run(collector.process_pending([TARGET], NOW))
    assert result["classified"] == 3 and not result["errors"]
    assert store.rows["https://publisher.example/batch/0"]["scope"] == "MACRO"
    for i in [1, 2]:
        item = store.rows[f"https://publisher.example/batch/{i}"]
        assert item["scope"] == "UNRESOLVED" and not item["company_codes"]
        assert "NEWS_CLASSIFICATION_SCOPE_INCONSISTENT" in item["classification_reason"]


def test_classifier_rejects_unknown_code_without_failing_valid_tag(monkeypatch):
    monkeypatch.setattr("app.news_collector.NewsStore", lambda _: MemoryStore())
    tags = [news_tag(0, "COMPANY", ["99999999"]), news_tag(1)]
    def response(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(
            {"items": [tag.model_dump() for tag in tags]})}}]})
    async def check():
        cfg = Settings(news_usage_authorization="SYNTHETIC_TEST_ONLY", openai_api_key="synthetic")
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            collector = NewsCollector(SimpleNamespace(store=object()), client, cfg)
            result = await collector.classify([{"title": "가상중공업 관련 보도"}, {"title": "금리 보도"}], [TARGET])
        assert result[0].scope == "UNRESOLVED" and not result[0].company_codes
        assert "NEWS_COMPANY_CODE_UNKNOWN" in result[0].reason
        assert result[1].scope == "MACRO"
    asyncio.run(check())
