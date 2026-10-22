import asyncio

# ruff: noqa: F811
from copy import deepcopy

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from test_analysis import FakeTools, fake_model, filing, initial, ledger  # noqa: F401

from disclosure_ai.harness.runtime import Harness
from disclosure_ai.services.documents import disclosure_type
from disclosure_ai.workflow.graph import AnalysisGraph


def test_type_uses_metadata_and_preserves_correction_without_table():
    assert disclosure_type({"changes": []}, "CORRECTION") == "CORRECTION"
    assert disclosure_type({"changes": []}) == "UNKNOWN"
    assert disclosure_type({"metadata_status": "FOUND", "report_name": "공급계약"}) == "NEW"
    assert disclosure_type({"metadata_status": "FOUND", "report_name": "[기재정정]공급계약"}) == "CORRECTION"
    assert disclosure_type({"metadata_status": "FOUND", "report_name": "[기재정정]공급계약"}, "NEW") == "UNKNOWN"


@pytest.mark.parametrize("kind", ["NEW", "CORRECTION"])
@pytest.mark.parametrize("outcome", ["FACT_UPDATE", "NO_IMPACT", "HOLD"])
def test_both_types_share_rag_perspectives_and_reanalysis(ledger, kind, outcome):
    source = {"document_id": "filing:1", "location": "line:1",
              "quote": "계약금액은 80입니다."}
    memo_text = "계약금액은 100입니다."
    base_inputs, observed = [], []

    class Tools(FakeTools):
        async def call(self, name, args):
            if name == "disclosure_get_document":
                self.calls.append(name)
                f = deepcopy(filing())
                f["documents"][0]["text"] = source["quote"]
                f["changes"] = [{**source, "label": "계약금액", "before": "100", "after": "80"}]
                return f
            if name == "search_evidence":
                self.calls.append(name)
                return {"documents": [{"document_id": "filing:1", "text": source["quote"]}],
                        "sources": [source]}
            return await super().call(name, args)

    async def model(role, context, schema):
        if role == "base":
            base_inputs.append(context)
            return {"summary": "공시 내용을 확인했습니다.",
                    "proposals": [{"claim_id": "1", "impact_type": outcome,
                                   "before_text": memo_text, "after_text": source["quote"] if outcome == "FACT_UPDATE" else None,
                                   "reason": "확인한 공시와 메모를 비교했습니다.", "evidence": [source]}],
                    "selected": [{"perspective_type": "FINANCE", "selection_reason": "금액의 영향을 확인합니다.", "question": "반영 여부를 확인합니다."}],
                    "no_additional_analysis_reason": None,
                    "limitations": ["관련 근거가 부족하여 수정을 보류합니다."] if outcome == "HOLD" else []}
        if role == "perspective":
            observed.append(context["observations"])
            if not context["observations"]:
                return {"status": "NEEDS_TOOLS", "findings": "", "sources": [],
                        "requests": [{"tool": "local_search", "query": "계약금액"}], "limitations": []}
            return {"status": "COMPLETED", "findings": "공시 금액을 확인했습니다. 기존 반영액은 추가 확인이 필요합니다.",
                    "sources": [source], "requests": [], "limitations": []}
        return await fake_model(role, context, schema)

    async def check():
        tools = Tools()
        run = AnalysisGraph(Harness("task", ledger, model), tools, InMemorySaver())
        state = initial()
        state["request"]["disclosure_type"] = kind
        result = await run.graph.ainvoke(state, {"configurable": {"thread_id": "typed"}})
        assert base_inputs[0]["analysis_type"] == kind
        assert tools.calls.count("ensure_analysis_index") == 1
        assert tools.calls.count("search_evidence") == 2
        assert len(observed) == 2 and observed[1]
        assert result["results"]["FINANCE"]["status"] == "COMPLETED"
        assert result["memo"]["text"] == memo_text
        report = result["report"]["report_json"]
        assert report["analysis_type"] == kind
        if kind == "NEW":
            assert not result["filing"]["changes"] and not report["corrections"]
            assert all("before" not in row and "after" not in row for row in base_inputs[0]["context"])
            assert "| 정정 전 |" not in result["report"]["content"]
        if outcome == "NO_IMPACT":
            assert "수정 없음:" in result["report"]["content"]
            assert "유지 제안" in result["report"]["content"]
        elif outcome == "HOLD":
            assert not report["base"]["proposals"]
            assert any("보류" in text for text in report["warnings"])
        else:
            assert report["base"]["proposals"][0]["after_text"] == source["quote"]

    asyncio.run(check())


@pytest.mark.parametrize("kind", ["CORRECTION", "UNKNOWN"])
def test_missing_table_does_not_select_new_path(ledger, kind):
    contexts = []

    class Tools(FakeTools):
        async def call(self, name, args):
            result = await super().call(name, args)
            if name == "disclosure_get_document":
                result["changes"] = []
                result["complete_correction_table"] = False
            return result

    async def model(role, context, schema):
        if role == "base":
            contexts.append(context)
        return await fake_model(role, context, schema)

    async def check():
        state = initial()
        state["request"]["disclosure_type"] = kind
        run = AnalysisGraph(Harness("task", ledger, model), Tools(), InMemorySaver())
        result = await run.graph.ainvoke(state, {"configurable": {"thread_id": "missing-table"}})
        assert contexts[0]["analysis_type"] == kind
        assert result["report"]["report_json"]["analysis_type"] == kind
        assert any("정정표" in text if kind == "CORRECTION" else "유형" in text
                   for text in result["report"]["report_json"]["warnings"])

    asyncio.run(check())
