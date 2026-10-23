import asyncio
from uuid import uuid4

import pytest

# ruff: noqa: F811
from langgraph.checkpoint.memory import InMemorySaver
from test_analysis import FakeTools, fake_model, initial, ledger  # noqa: F401

from disclosure_ai.harness.runtime import Harness
from disclosure_ai.workflow.graph import AnalysisGraph


@pytest.mark.parametrize("kind", ["NEW", "CORRECTION"])
def test_four_perspectives_and_news_rag_article_reanalysis(ledger, kind):
    article_id = str(uuid4())
    source = {
        "document_id": "news:verified",
        "location": "news:title",
        "quote": "국제 원자재 가격 상승 보도",
        "url": "https://n.news.naver.com/mnews/article/001/0000000001",
        "published_at": "2026-10-19T01:00:00Z",
    }
    observed = []

    class Tools(FakeTools):
        async def call(self, name, args):
            if name == "search_market_news":
                self.calls.append(name)
                return {
                    "articles": [
                        {"id": article_id, "title": "원자재 가격 상승", "url": source["url"]}
                    ],
                    "as_of": "2026-10-20T01:00:00Z",
                    "range_start": "2026-10-13T01:00:00Z",
                    "title_only": True,
                    "documents": [
                        {
                            "document_id": source["document_id"],
                            "text": source["quote"],
                            "url": source["url"],
                            "published_at": source["published_at"],
                            "article_snapshot": {
                                "title": source["quote"],
                                "url": source["url"],
                                "published_at": source["published_at"],
                            },
                        }
                    ],
                    "sources": [source],
                }
            if name == "read_market_news":
                pytest.fail("본문 조회를 요청하면 안 됩니다.")
            return await super().call(name, args)

    async def model(role, context, schema):
        if role == "base":
            result = await fake_model(role, context, schema)
            assert context["market_news"]["articles"]
            result["selected"] = [
                {
                    "perspective_type": p,
                    "selection_reason": "연결 근거를 확인합니다.",
                    "question": "영향은 무엇입니까?",
                }
                for p in ["FINANCE", "FX_HEDGE", "INDUSTRY_CONTRACT", "MARKET_NEWS"]
            ]
            return result
        if role == "perspective" and context["selection"]["perspective_type"] == "MARKET_NEWS":
            observed.append(context["observations"])
            if not context["observations"]:
                return {
                    "status": "NEEDS_TOOLS",
                    "findings": "",
                    "sources": [],
                    "limitations": [],
                    "requests": [{"tool": "search_market_news", "query": "원자재 시황"}],
                }
            return {
                "status": "COMPLETED",
                "findings": "원자재 가격 상승이 보도됐습니다. 기존 원가 가정의 검토가 필요하며 제목만으로 금액을 판단할 수 없습니다.",
                "sources": [source],
                "requests": [],
                "limitations": [],
            }
        return await fake_model(role, context, schema)

    async def check():
        tools = Tools()
        state = initial()
        state["request"]["disclosure_type"] = kind
        result = await AnalysisGraph(
            Harness("task", ledger, model), tools, InMemorySaver()
        ).graph.ainvoke(state, {"configurable": {"thread_id": "market"}})
        assert set(result["results"]) == {"FINANCE", "FX_HEDGE", "INDUSTRY_CONTRACT", "MARKET_NEWS"}
        assert result["results"]["MARKET_NEWS"]["status"] == "COMPLETED", str(
            result["results"]["MARKET_NEWS"].get("limitations")
        )
        assert tools.calls.count("search_market_news") == 2 and len(observed) == 2
        assert source["url"] in result["report"]["content"]
        assert "시황 뉴스" in result["report"]["content"]
        assert result["report"]["report_json"]["news_snapshots"][0]["url"] == source["url"]
        assert "시황 기준 시각(분석 요청)" in result["report"]["content"]

    asyncio.run(check())


def test_market_agent_can_defer_without_forced_article_choice(ledger):
    from types import SimpleNamespace

    from disclosure_ai.workflow.perspectives import perspective

    async def model(role, context, schema):
        assert role == "perspective"
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "findings": "",
            "sources": [],
            "requests": [],
            "limitations": ["NEWS_NO_MATCH_IN_STORE: 연결되는 저장 제목이 없습니다."],
        }

    async def check():
        state = initial()
        state.update(
            selection={
                "perspective_type": "MARKET_NEWS",
                "question": "시황 확인",
                "selection_reason": "시황 확인",
            },
            market_news={"articles": []},
            jobs={},
            context=[],
            memo={},
            documents=[],
            base={"selected": []},
        )
        run = SimpleNamespace(h=Harness("task", ledger, model), tools=FakeTools())
        result = await perspective(run, state)
        assert result["results"]["MARKET_NEWS"]["status"] == "INSUFFICIENT_EVIDENCE", str(
            result["results"]["MARKET_NEWS"].get("limitations")
        )
        assert "NEWS_NO_MATCH_IN_STORE" in result["results"]["MARKET_NEWS"]["limitations"][0]

    asyncio.run(check())


def test_four_perspectives_leave_report_and_checker_budget(ledger):
    async def model(role, context, schema):
        if role == "base":
            answer = await fake_model(role, context, schema)
            answer["selected"] = [
                {
                    "perspective_type": kind,
                    "selection_reason": "합성 예산 검증",
                    "question": "추가 근거가 필요합니까?",
                }
                for kind in ["FINANCE", "FX_HEDGE", "INDUSTRY_CONTRACT", "MARKET_NEWS"]
            ]
            return answer
        if role == "perspective":
            return {
                "status": "NEEDS_TOOLS",
                "findings": "",
                "sources": [],
                "limitations": [],
                "requests": [{"tool": "local_search", "query": "공통 합성 질문"}],
            }
        return await fake_model(role, context, schema)

    async def check():
        output = await AnalysisGraph(
            Harness("task", ledger, model), FakeTools(), InMemorySaver()
        ).graph.ainvoke(initial(), {"configurable": {"thread_id": "budget-four"}})
        assert output["report"]["content"] and output["output"]["report_id"] == "report"
        assert len(output["results"]) == 4
        assert all(result["status"] == "LIMIT_REACHED" for result in output["results"].values())
        assert ledger.row("task")["turns"] <= 12
        assert any(e["kind"] == "OUTPUT_CHECK_END" for e in ledger.events("task"))

    asyncio.run(check())
