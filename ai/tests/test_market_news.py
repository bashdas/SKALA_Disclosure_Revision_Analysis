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
    source = {"document_id": "news:verified", "location": "article:body", "quote": "국제 원자재 가격이 상승했습니다.",
              "url": "https://n.news.naver.com/mnews/article/001/0000000001", "published_at": "2026-10-19T01:00:00Z"}
    observed = []
    class Tools(FakeTools):
        async def call(self, name, args):
            if name == "search_market_news":
                self.calls.append(name)
                return {"articles": [{"id": article_id, "title": "원자재 가격 상승", "url": source["url"]}],
                        "as_of": "2026-10-20T01:00:00Z"}
            if name == "read_market_news":
                self.calls.append(name)
                assert args["article_ids"] == [article_id]
                return {"documents": [{"document_id": source["document_id"], "text": source["quote"], "url": source["url"], "published_at": source["published_at"]}], "sources": [source]}
            return await super().call(name, args)
    async def model(role, context, schema):
        if role == "news_plan":
            return {"article_ids": [article_id], "search_query": None, "reason": "원자재 뉴스 본문 확인"}
        if role == "base":
            result = await fake_model(role, context, schema)
            assert context["market_news"]["articles"]
            result["selected"] = [{"perspective_type": p, "selection_reason": "연결 근거를 확인합니다.", "question": "영향은 무엇입니까?"}
                for p in ["FINANCE", "FX_HEDGE", "INDUSTRY_CONTRACT", "MARKET_NEWS"]]
            return result
        if role == "perspective" and context["selection"]["perspective_type"] == "MARKET_NEWS":
            observed.append(context["observations"])
            if not context["observations"]:
                return {"status": "NEEDS_TOOLS", "findings": "", "sources": [], "limitations": [],
                        "requests": [{"tool": "read_market_news", "query": "원문 확인", "article_ids": [article_id]}]}
            return {"status": "COMPLETED", "findings": "원자재 가격 상승을 확인했습니다. 기존 원가 가정의 검토가 필요합니다.",
                    "sources": [source], "requests": [], "limitations": []}
        return await fake_model(role, context, schema)
    async def check():
        tools = Tools()
        state = initial()
        state["request"]["disclosure_type"] = kind
        result = await AnalysisGraph(Harness("task", ledger, model), tools, InMemorySaver()).graph.ainvoke(
            state, {"configurable": {"thread_id": "market"}})
        assert set(result["results"]) == {"FINANCE", "FX_HEDGE", "INDUSTRY_CONTRACT", "MARKET_NEWS"}
        assert result["results"]["MARKET_NEWS"]["status"] == "COMPLETED"
        assert tools.calls.count("read_market_news") == 1 and len(observed) == 1
        assert source["url"] in result["report"]["content"]
        assert "시황 뉴스" in result["report"]["content"]
        assert "시황 기준 시각(분석 요청)" in result["report"]["content"]
    asyncio.run(check())


def test_market_agent_can_defer_without_forced_article_choice(ledger):
    from types import SimpleNamespace

    from disclosure_ai.workflow.perspectives import perspective
    async def model(role, context, schema):
        assert role == "news_plan"
        return {"article_ids": [], "search_query": None, "reason": "질문과 연결되는 저장 기사가 없습니다."}
    async def check():
        run = SimpleNamespace(h=Harness("task", ledger, model), tools=FakeTools())
        result = await perspective(run, {"selection": {"perspective_type": "MARKET_NEWS", "question": "시황 확인", "selection_reason": "시황 확인"},
            "request": initial()["request"], "market_news": {"articles": []}, "jobs": {}})
        assert result["results"]["MARKET_NEWS"]["status"] == "INSUFFICIENT_EVIDENCE"
        assert result["results"]["MARKET_NEWS"]["limitations"] == ["질문과 연결되는 저장 기사가 없습니다."]
    asyncio.run(check())
