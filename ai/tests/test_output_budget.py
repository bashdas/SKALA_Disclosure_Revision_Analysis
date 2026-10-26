import asyncio

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from test_analysis import fake_model, initial, ledger  # noqa: F401
from test_disclosure_review import FACT, SOURCE, Tools, point

from disclosure_ai.harness.runtime import Harness
from disclosure_ai.schemas import OutputReview
from disclosure_ai.workflow.graph import AnalysisGraph


@pytest.mark.parametrize("invalid_index", [False, True])
def test_large_sources_are_packed_as_complete_views_in_one_bounded_call(ledger, invalid_index):  # noqa: F811
    long_source = {"document_id": "filing:past", "location": "line:1",
                   "quote": "이것은 과거 계약의 전체 본문이며 현재 공시 사실이 아닙니다. " * 6000}
    small = point()
    large = point(title="과거 원문이 너무 긴 관점입니다.", question="과거 계약과 이번 계약의 범위를 비교합니까?",
                  evidence=[SOURCE, long_source])
    calls = []

    async def model(role, context, schema):
        calls.append(role)
        assert role == "output_check"
        assert harness.fits_model_input(role, context, schema)
        text = str(context)
        assert large["title"] not in text and large["question"] not in text
        assert small["title"] in text and small["condition"] in text
        assert len(context["sentences"]) < 128
        indices = [s["index"] for s in context["sentences"]]
        return {"safe_indices": [999] if invalid_index else indices}

    harness = Harness("task", ledger, model)

    async def check():
        payload = {"results": {"FINANCE": {"status": "COMPLETED", "findings": "확인한 범위의 재무 분석입니다.", "sources": [SOURCE]}}, "base": {"review_points": [large, small]},
                   "summary_claims": [{"text": FACT, "evidence": [SOURCE]}]}
        checked, warnings = await harness.review_output(
            payload, grounding=True, advisory=True, current_document_ids={SOURCE["document_id"]})
        assert len(checked["base"]["review_points"]) == 2
        assert checked["results"]["FINANCE"]["findings"]
        assert payload["base"]["review_points"] == [large, small]
        assert any("OUTPUT_CHECK_PARTIAL" in warning for warning in warnings)
        assert calls == ["output_check"] and ledger.row("task")["turns"] == 1
        assert ledger.row("task")["tokens"] < 80000
        assert harness.model_input_spec("output_check", {}, OutputReview)[1:3] == (24000, 4000)

    asyncio.run(check())


def test_excess_sentences_do_not_block_small_grounded_summary(ledger):  # noqa: F811
    async def model(role, context, schema):
        assert len(context["sentences"]) <= 128
        return {"safe_indices": [s["index"] for s in context["sentences"]]}

    async def check():
        harness = Harness("task", ledger, model)
        payload = {"base": {"review_points": [point()]}, "summary_claims": [{"text": FACT, "evidence": [SOURCE]}],
                   "extra": ["항목 " + str(i) for i in range(200)]}
        checked, warnings = await harness.review_output(payload, grounding=True, advisory=True)
        assert checked["summary_claims"][0]["text"] == FACT
        assert checked["base"]["review_points"]
        assert any("OUTPUT_CHECK_PARTIAL" in warning for warning in warnings)
        assert ledger.row("task")["turns"] == 1

    asyncio.run(check())


def test_failed_check_preserves_completed_analysis_with_warning(ledger):  # noqa: F811
    async def model(role, context, schema):
        if role == "base":
            answer = await fake_model(role, context, schema)
            answer["review_points"] = [point()]
            if role == "base" and "selected" in answer:
                answer["not_selected"] = [{"perspective_type": kind, "reason": "기본 분석으로 충분합니다."}
                    for kind in ["INDUSTRY_CONTRACT", "FINANCE", "FX_HEDGE", "MARKET_NEWS"]
                    if kind not in {s["perspective_type"] for s in answer["selected"]}]
            return answer
        if role == "output_check":
            raise RuntimeError("CHECK_UNAVAILABLE")
        return await fake_model(role, context, schema)

    async def check():
        harness = Harness("task", ledger, model)
        state = await AnalysisGraph(harness, Tools(), InMemorySaver()).graph.ainvoke(
            initial(), {"configurable": {"thread_id": "failed-check"}})
        data = state["report"]["report_json"]
        assert data["base"]["review_points"]
        assert data["summary_claims"]
        assert any("OUTPUT_CHECK_FAILED" in warning for warning in data["warnings"])
        assert not any("SUMMARY_SOURCE_FALLBACK" in warning for warning in data["warnings"])
        assert ledger.row("task")["turns"] == 3

    asyncio.run(check())
