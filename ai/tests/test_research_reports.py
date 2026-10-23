import asyncio
import json
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from test_analysis import FakeTools, fake_model, initial

from disclosure_ai.harness.ledger import Ledger
from disclosure_ai.harness.runtime import Harness
from disclosure_ai.services.research import ResearchIndex, chunks, verified_research
from disclosure_ai.workflow import shared
from disclosure_ai.workflow.graph import AnalysisGraph

MEMO = "aa58e157-b7b1-4270-8c9f-efe30aabed8c"


def request():
    return {
        **initial()["request"],
        "memo_id": MEMO,
        "corp_code": "00126478",
        "company_name_snapshot": "삼성중공업",
    }


def vector(axis=0):
    return [float(index == axis) for index in range(1536)]


@pytest.fixture
def ledger(tmp_path):
    value = Ledger(str(tmp_path / "state.sqlite"))
    value.begin("task", "fixed")
    yield value
    value.db.close()


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    path = tmp_path / "reports.json"
    path.write_text(
        json.dumps(
            [
                {
                    "report_id": "im-test",
                    "title": "삼성중공업 실적 전망",
                    "company_name": "삼성중공업",
                    "corp_code": "00126478",
                    "published_at": "2026-02-02",
                    "url": None,
                    "source_file": "report.pdf",
                    "text": "[1쪽]\n실적은 증가할 전망입니다.\n[2쪽]\n계약 이행과 잔금 회수를 전제로 합니다.",
                }
            ],
            ensure_ascii=False,
        )
    )
    monkeypatch.setenv("AI_RESEARCH_REPORTS_PATH", str(path))
    return path


def test_embedding_cache_and_company_date_filter(ledger, catalog):
    calls = []

    async def embed(texts):
        calls.append(texts)
        return [vector(0 if "잔금" in text else 1) for text in texts]

    async def check():
        index = ResearchIndex(ledger, embed)
        found = await index.search(request(), {}, "org:memo:1", "잔금 회수")
        assert found["sources"][0]["location"].startswith("page:2:")
        assert found["research_reports"][0]["corp_code"] == "00126478"
        assert found["documents"][0]["text"].startswith("[1쪽]")
        await ResearchIndex(ledger, embed).search(request(), {}, "org:memo:1", "잔금 회수")
        assert len(calls[0]) == 3 and calls[1] == ["잔금 회수"]
        await index.search(request(), {}, "other-org:memo:1", "잔금 회수")
        assert len(calls[-1]) == 3
        for changed in (
            {"corp_code": "00000001"},
            {"disclosure_receipt_no": "20260101000001"},
        ):
            absent = await index.search({**request(), **changed}, {}, "org", "잔금")
            assert not absent["documents"]
        assert len(calls) == 3
        for changed in ({"base_memo_version": 2}, {"memo_id": str(uuid4())}):
            found = await index.search({**request(), **changed}, {}, "org:memo:1", "잔금")
            assert found["documents"]
        independent = {k: v for k, v in request().items() if k not in {"memo_id", "base_memo_version"}}
        assert (await index.search(independent, {}, "org:memo:1", "잔금"))["documents"]
        # 같은 리포트 ID여도 내용이 바뀐 조각은 새로 임베딩합니다.
        data = json.loads(catalog.read_text())
        data[0]["text"] += "\n회수 시점을 확인합니다."
        catalog.write_text(json.dumps(data))
        await ResearchIndex(ledger, embed).search(request(), {}, "org:memo:1", "잔금 회수")
        assert len(calls[-1]) == 2

    asyncio.run(check())


def test_company_reports_follow_official_filing_date(ledger, catalog):
    index = ResearchIndex(ledger)
    assert index.eligible(request(), {"filed_at": "2026-02-02"})
    assert not index.eligible(request(), {"filed_at": "2026-02-01"})
    sec_request = {**request(), "disclosure_receipt_no": "SEC:1:0000000000-26-000001"}
    assert not index.eligible(sec_request, {})
    assert index.eligible(sec_request, {"filed_at": "2026-02-02"})
    assert not index.eligible({**request(), "corp_code": "00000001"}, {"filed_at": "2026-02-02"})


@pytest.mark.parametrize("value", [[], [0.0] * 1536, [float("nan")] * 1536, [1.0]])
def test_invalid_embedding_rejected(ledger, value):
    async def embed(texts):
        return [value] if value else []

    with pytest.raises(ValueError):
        asyncio.run(ResearchIndex(ledger, embed).vectors(["계약"]))


def test_packaged_report_and_page_locations(ledger, monkeypatch):
    monkeypatch.delenv("AI_RESEARCH_REPORTS_PATH", raising=False)
    index = ResearchIndex(ledger)
    report = index.eligible(request(), {})[0]
    assert report.report_id == "im-010140-20260202"
    assert len(report.text) == 18163
    fragments = chunks(report)
    assert any(source["location"].startswith("page:2:") for source in fragments)
    assert all(source["quote"] in report.text for source in fragments)
    assert not index.eligible(
        {**request(), "disclosure_receipt_no": "SEC:1:0000000000-26-000001"}, {}
    )


@pytest.mark.parametrize("integrated", [False, True])
def test_graph_renders_research_with_existing_save_contract(ledger, catalog, monkeypatch, integrated):
    captured = {}

    async def vectors(self, texts):
        return [vector() for _ in texts]

    monkeypatch.setattr(ResearchIndex, "vectors", vectors)

    async def model(role, context, schema):
        answer = {} if role in {"research", "news_plan"} else await fake_model(role, context, schema)
        if integrated and role == "base":
            assert context["history_context"]
            assert context["research_reports"] and context["market_news"]["articles"]
            answer["selected"] = [
                {"perspective_type": kind, "selection_reason": "변경 영향을 확인합니다.", "question": "영향은 무엇입니까?"}
                for kind in ("FINANCE", "INDUSTRY_CONTRACT", "FX_HEDGE", "MARKET_NEWS")
            ]
        if role == "news_plan":
            return {"article_ids": ["news-id"], "search_query": None, "reason": "시황 본문을 확인합니다."}
        if integrated and role == "perspective" and context["selection"]["perspective_type"] == "MARKET_NEWS":
            return {"status": "COMPLETED", "findings": "원자재 가격 변화를 확인했습니다.",
                    "sources": [news_source], "requests": [], "limitations": []}
        if role == "research":
            answer["limitations"] = []
            captured.update(context)
            source = next(
                source
                for source in context["context"]
                if source["document_id"].startswith("research:")
            )
            filing = next(
                source for source in context["context"] if source["document_id"] == "filing:1"
            )
            filing = {
                "document_id": filing["document_id"],
                "location": filing["location"],
                "quote": "",
            }
            report_source = {key: source[key] for key in ("document_id", "location", "quote")}
            evidence = [report_source, filing]
            answer["memo_supplements"] = [
                {
                    "report_document_id": source["document_id"],
                    "report_location": source["location"],
                    "text": "계약 변경 이후 잔금 회수 여부를 추가 확인합니다.",
                    "reason": "공시 변경을 반영해 검토 항목을 보완합니다.",
                    "evidence": evidence,
                }
            ]
            answer["report_revisions"] = [
                {
                    "document_id": source["document_id"],
                    "location": source["location"],
                    "after_text": None,
                    "reason": "기존 전망의 계약 가정 반영 여부를 추가 확인합니다.",
                    "evidence": evidence,
                }
            ]
        return answer

    news_source = {"document_id": "news:1", "location": "article:body", "quote": "원자재 가격이 상승했습니다.",
                   "url": "https://n.news.naver.com/mnews/article/001/0000000001"}

    class IntegratedTools(FakeTools):
        async def call(self, name, args):
            if name == "history_family":
                return {"items": [{"receipt_no": "20260201000001", "is_correction": False, "filed_at": "2026-02-01"},
                                  {"receipt_no": request()["disclosure_receipt_no"]}],
                        "source_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=" + request()["disclosure_receipt_no"]}
            if name == "history_document":
                return {"corp_code": "00126478", "metadata_status": "FOUND", "report_name": "공급계약", "filed_at": "2026-02-01",
                        "documents": [{"document_id": "history:1", "text": "기존 계약금액은 100입니다."}]}
            if name == "search_market_news":
                return {"articles": [{"id": "news-id", "title": "원자재 가격 상승", "url": news_source["url"]}]}
            if name == "read_market_news":
                assert args["article_ids"] == ["news-id"]
                return {"documents": [{"document_id": "news:1", "text": news_source["quote"], "url": news_source["url"]}],
                        "sources": [news_source]}
            return await super().call(name, args)

    async def check():
        tools = IntegratedTools() if integrated else FakeTools()
        graph = AnalysisGraph(Harness("task", ledger, model), tools, InMemorySaver()).graph
        state = {**initial(), "request": {**request(), "disclosure_type": "CORRECTION"}}
        result = await graph.ainvoke(state, {"configurable": {"thread_id": "research"}})
        report = result["report"]
        assert captured["research_reports"][0]["corp_code"] == "00126478"
        data = report["report_json"]
        assert data["report_revisions"][0]["memo_id"] == MEMO
        assert data["report_revisions"][0]["before_text"] in next(
            doc["text"] for doc in result["documents"] if doc["document_id"] == "research:im-test"
        )
        assert len(data["memo_supplements"]) == 1
        if integrated:
            assert data["disclosure_history"]["status"] == "ACQUIRED"
            assert len(data["results"]) == 4
            assert data["results"]["MARKET_NEWS"]["status"] == "COMPLETED"
            assert news_source["url"] in report["content"]
        assert "증권사 리포트 수정 검토" in report["content"]
        assert "메모 보완 제안" in report["content"]
        assert "메모 영향 판단 보류" not in report["content"]
        assert "page:1:" in report["content"]
        assert tools.calls.count("business_save_report") == 1
        assert result["memo"]["text"] == "계약금액은 100입니다."
        assert set(report) == {
            "content",
            "report_json",
            "has_warnings",
            "no_additional_analysis_reason",
            "generated_at",
        }
        return result

    state = asyncio.run(check())
    data = state["base"]
    data["report_revisions"][0]["location"] = "page:999:lines:1-2"
    assert not verified_research(data, state)["report_revisions"]
    data["memo_supplements"][0]["evidence"] = []
    assert not verified_research(data, state)["memo_supplements"]


def test_embedding_failure_keeps_existing_analysis(ledger, catalog, monkeypatch):
    async def fail(self, texts):
        raise RuntimeError("embedding offline")

    monkeypatch.setattr(ResearchIndex, "vectors", fail)

    async def check():
        graph = AnalysisGraph(
            Harness("task", ledger, fake_model), FakeTools(), InMemorySaver()
        ).graph
        state = await graph.ainvoke(
            {**initial(), "request": request()}, {"configurable": {"thread_id": "failure"}}
        )
        assert state["output"]["report_id"] == "report"
        assert any("리포트 검색 미완료" in warning for warning in state["warnings"])
        assert not state["report"]["report_json"]["report_revisions"]

    asyncio.run(check())


def test_shared_search_also_searches_company_reports(ledger, catalog, monkeypatch):
    async def vectors(self, texts):
        return [vector() for _ in texts]

    monkeypatch.setattr(ResearchIndex, "vectors", vectors)

    async def check():
        run = AnalysisGraph(Harness("task", ledger, fake_model), FakeTools(), InMemorySaver())
        state = {
            **initial(),
            "request": request(),
            "filing": {},
            "documents": [],
            "research_reports": [{"document_id": "research:im-test"}],
            "lookups": [{"tool": "search_evidence", "args": {"query": "잔금"}, "kind": "FINANCE"}],
        }
        result = await shared.lookup(run, state)
        assert any(
            source["document_id"].startswith("research:")
            for source in result["lookup_results"][0]["response"]["sources"]
        )

    asyncio.run(check())


def test_real_model_input_keeps_each_document_when_compacted(ledger):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from disclosure_ai.schemas import BaseAnalysis

    async def check():
        answer = BaseAnalysis.model_validate(await fake_model("base", {}, BaseAnalysis))
        parse = AsyncMock(
            return_value=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(parsed=answer))],
                usage=None,
            )
        )
        harness = Harness("task", ledger)
        harness.client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(parse=parse))
        )
        sources = [
            {
                "document_id": f"filing:{i}",
                "location": f"row:{i}",
                "quote": "계약 취소와 비용 회수 계획을 확인합니다. " * 250,
            }
            for i in range(4)
        ]
        sources += [
            {
                "document_id": "research:report",
                "location": f"page:{i}:lines:1-10",
                "quote": "실적 전망의 반영 여부를 확인합니다. " * 250,
            }
            for i in range(3)
        ]
        await harness.model(
            "base",
            {
                "analysis_type": "CORRECTION",
                "context": sources,
                "research_reports": [{"document_id": "research:report"}],
            },
            BaseAnalysis,
        )
        sent = json.loads(parse.call_args.kwargs["messages"][1]["content"])
        assert sent["context_truncated"]
        assert {(source["document_id"], source["location"]) for source in sent["context"]} == {
            (source["document_id"], source["location"]) for source in sources
        }
        assert all(source["quote"] for source in sent["context"])

    asyncio.run(check())


def test_invalid_catalog_is_not_reused_after_validation_failure(ledger, catalog):
    reports = json.loads(catalog.read_text())
    catalog.write_text(json.dumps(reports + reports))
    index = ResearchIndex(ledger)
    for _ in range(2):
        with pytest.raises(ValueError, match="INVALID_RESEARCH_CATALOG"):
            index.eligible(request(), {})
    assert index.catalog is None
