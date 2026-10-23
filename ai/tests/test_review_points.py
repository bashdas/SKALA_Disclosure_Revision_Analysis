import asyncio

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from test_analysis import FakeTools, fake_model, initial, ledger  # noqa: F401

from disclosure_ai.harness.runtime import Harness
from disclosure_ai.workflow.graph import AnalysisGraph

MEMO = "SC 전환 확대가 로열티 성장의 핵심 가정입니다."
FACT = "기술이전 계약의 적용 제품 범위가 확대되었습니다."
MEMO_SOURCE = {"document_id": "memo:1:v1", "location": "memo", "quote": MEMO}
FILING_SOURCE = {"document_id": "filing:new", "location": "line:1:overview", "quote": FACT}


def point(evidence):
    return {
        "perspective_type": "FINANCE", "title": "로열티 성장 가정의 적용 범위 재검토",
        "memo_view": "기존 메모는 SC 전환 확대를 로열티 성장의 가정으로 봅니다.",
        "disclosure_fact": FACT,
        "reason": "적용 제품 확대가 기존 성장 가정에 반영되어 있는지 다시 확인해야 합니다.",
        "question": "확대된 제품의 로열티 조건과 상업화 시점이 기존 전망에 반영되어 있습니까?",
        "check_items": ["제품별 로열티 조건과 기존 전망의 반영 범위를 확인합니다."],
        "evidence": evidence,
    }


class Tools(FakeTools):
    async def call(self, name, args):
        if name == "disclosure_get_document":
            return {"documents": [{"document_id": "filing:new", "text": FACT}],
                    "changes": [], "report_name": "기술이전 계약 변경", "metadata_status": "FOUND"}
        if name == "business_get_memo":
            return {"document_id": "memo:1:v1", "text": MEMO, "version": 1}
        return await super().call(name, args)


@pytest.mark.parametrize("selected", [False, True])
def test_review_survives_without_editable_sentence_or_completed_deep_analysis(ledger, selected):  # noqa: F811
    seen = []

    async def model(role, context, schema):
        answer = await fake_model(role, context, schema)
        if role == "base":
            answer["review_points"] = [point([MEMO_SOURCE, FILING_SOURCE])]
            answer["selected"] = [{"perspective_type": "FINANCE",
                                   "selection_reason": "제품별 로열티 조건을 확인합니다.",
                                   "question": "기존 전망의 적용 범위는 무엇입니까?"}] if selected else []
        elif role == "perspective":
            assert context["review_points"][0]["memo_view"]
            seen.append(role)
            # 심화 조회가 미완료여도 근거 있는 기본 재검토 질문은 남아야 합니다.
        elif role == "report":
            assert context["facts"]["review_points"][0]["evidence_ids"]
            assert not context["facts"]["proposals"]
            seen.append(role)
        return answer

    async def check():
        state = await AnalysisGraph(Harness("task", ledger, model), Tools(), InMemorySaver()).graph.ainvoke(
            initial(), {"configurable": {"thread_id": "review"}},
        )
        report = state["report"]["report_json"]
        assert not report["base"]["proposals"]
        assert len(report["base"]["review_points"]) == 1
        assert report["memo_review"] is None
        assert {s["document_id"] for s in report["base"]["review_points"][0]["evidence"]} == {
            "memo:1:v1", "filing:new",
        }
        section = report["sections"]["review_points"]
        assert "기존 메모의 관점과 가정" in section and "검토 질문" in section
        assert "[근거 " in section
        assert not report["sections"]["suggestions"]
        assert "메모 영향 판단 보류" not in state["report"]["content"]
        assert seen.count("perspective") == int(selected)
        assert "report" in seen

    asyncio.run(check())


@pytest.mark.parametrize("evidence", [
    [MEMO_SOURCE, MEMO_SOURCE],
    [FILING_SOURCE, FILING_SOURCE],
    [MEMO_SOURCE, {**FILING_SOURCE, "quote": "이번 공시에 없는 실적입니다."}],
    [{**MEMO_SOURCE, "quote": "기존 메모에 없는 가정입니다."}, FILING_SOURCE],
    [MEMO_SOURCE, {**FILING_SOURCE, "document_id": "external:other"}],
])
def test_review_requires_both_original_memo_and_current_disclosure(ledger, evidence):  # noqa: F811
    async def model(role, context, schema):
        answer = await fake_model(role, context, schema)
        if role == "base":
            answer["review_points"] = [{**point(evidence), "title": "UNSUPPORTED_REVIEW"}]
        else:
            assert "UNSUPPORTED_REVIEW" not in str(context)
        return answer

    async def check():
        state = await AnalysisGraph(Harness("task", ledger, model), Tools(), InMemorySaver()).graph.ainvoke(
            initial(), {"configurable": {"thread_id": "unlinked"}},
        )
        assert state["base"]["review_points"] == []
        assert state["report"]["report_json"]["base"]["review_points"] == []
        assert "UNSUPPORTED_REVIEW" not in state["report"]["content"]
        assert any("양쪽의 근거" in text for text in state["base"]["limitations"])

    asyncio.run(check())
