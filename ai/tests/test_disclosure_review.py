import asyncio
import time

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError
from test_analysis import FakeTools, fake_model, initial, ledger  # noqa: F401

from disclosure_ai.harness.runtime import Harness
from disclosure_ai.schemas import BaseAnalysis, ReviewPoint
from disclosure_ai.services.documents import validated_review_points
from disclosure_ai.workflow.graph import AnalysisGraph

FACT = "미국 달러로 지급하는 계약 대금의 지급일이 2026년 11월에서 2027년 2월로 연기됐습니다."
MEMO = "이 회사는 국내 신규 공장 건설에 집중하고 있습니다."
SOURCE = {"document_id": "filing:current", "location": "line:1:overview", "quote": FACT}
MEMO_SOURCE = {"document_id": "memo:1:v1", "location": "memo", "quote": MEMO}


def point(**extra):
    return {
        "view_type": "DISCLOSURE_REVIEW", "perspective_type": "FX_HEDGE",
        "title": "대금 수취 일정과 헤지 만기 및 금액의 대응을 확인합니다.",
        "memo_view": None,
        "condition": "해당 달러 대금을 대상으로 환헤지를 보유한 경우입니다.",
        "disclosure_fact": FACT,
        "reason": "해당 대금의 환헤지를 보유했다면 수취 일정과 헤지 만기가 어긋나는지 확인해야 합니다.",
        "question": "해당 대금의 환헤지를 보유한 경우 만기와 금액이 변경된 수취 일정에 대응합니까?",
        "check_items": ["해당 대금의 환헤지 보유 여부와 만기 및 대상 금액을 확인합니다."],
        "evidence": [SOURCE], **extra,
    }


class Tools(FakeTools):
    async def call(self, name, args):
        if name == "disclosure_get_document":
            return {"documents": [{"document_id": SOURCE["document_id"], "text": FACT}],
                    "changes": [], "report_name": "대금 지급일 변경", "metadata_status": "FOUND"}
        if name == "business_get_memo":
            return {"document_id": MEMO_SOURCE["document_id"], "text": MEMO, "version": 1}
        return await super().call(name, args)


def test_view_schema_defaults_legacy_and_limits_five():
    legacy = point(view_type="MEMO_REVIEW", memo_view=MEMO, evidence=[MEMO_SOURCE, SOURCE])
    legacy.pop("view_type")
    legacy.pop("condition")
    parsed = ReviewPoint.model_validate(legacy)
    assert parsed.view_type == "MEMO_REVIEW" and parsed.condition is None
    assert ReviewPoint.model_validate(point()).memo_view is None
    with pytest.raises(ValidationError):
        ReviewPoint.model_validate(point(memo_view="만들어낸 메모 가정입니다."))
    with pytest.raises(ValidationError):
        ReviewPoint.model_validate(point(view_type="MEMO_REVIEW"))
    base = {"summary": "", "proposals": [], "selected": [], "limitations": [],
            "no_additional_analysis_reason": None}
    assert len(BaseAnalysis.model_validate({**base, "review_points": [point()] * 5}).review_points) == 5
    with pytest.raises(ValidationError):
        BaseAnalysis.model_validate({**base, "review_points": [point()] * 6})


def test_disclosure_evidence_must_be_current_and_questions_deduplicated():
    filing = {"documents": [{"document_id": SOURCE["document_id"], "text": FACT}]}
    memo = {"document_id": MEMO_SOURCE["document_id"], "text": MEMO}
    documents = [*filing["documents"], memo, {"document_id": "filing:past", "text": FACT}]
    past = {**SOURCE, "document_id": "filing:past"}
    cases = [point(evidence=[MEMO_SOURCE]), point(evidence=[past]),
             point(evidence=[{**SOURCE, "quote": "이번 공시에 없는 문장입니다."}])]
    assert validated_review_points(cases, filing, memo, documents, []) == []
    linked = point(view_type="MEMO_REVIEW", memo_view=MEMO, evidence=[MEMO_SOURCE, SOURCE])
    accepted = validated_review_points([point(), linked], filing, memo, documents, [])
    assert len(accepted) == 1 and accepted[0]["view_type"] == "DISCLOSURE_REVIEW"


@pytest.mark.parametrize("reject", [None, "condition", "question", "disclosure_fact", "reason", "failure", "budget"])
def test_new_view_checks_all_fields_and_fails_closed_without_extra_calls(ledger, reject):  # noqa: F811
    seen = []

    async def model(role, context, schema):
        seen.append(role)
        answer = await fake_model(role, context, schema)
        if role == "base":
            answer["review_points"] = [point()]
        elif role == "report":
            assert context["facts"]["review_points"][0]["memo_view"] is None
            answer = {"summary": [{"text": FACT, "evidence_ids": [next(iter(context["evidence"]))]}]}
            if reject == "budget":
                ledger.db.execute("UPDATE runs SET started=? WHERE id='task'", (time.time() - 115,))
                ledger.db.commit()
        elif role == "output_check":
            if reject == "failure":
                raise RuntimeError("CHECK_UNAVAILABLE")
            rows = context["sentences"]
            new = [s for s in rows if s.get("view_type") == "DISCLOSURE_REVIEW"]
            assert any(s["kind"] == "review_question" for s in new)
            assert any(s["kind"] == "review_condition" for s in new)
            assert all(context["evidence"][ref]["current_disclosure"]
                       for s in new for ref in s["evidence_ids"])
            assert "DISCLOSURE_REVIEW" not in [s["text"] for s in rows]
            answer["safe_indices"] = [s["index"] for s in rows if s.get("kind") != "review_" + str(reject)]
        return answer

    async def check():
        harness = Harness("task", ledger, model)
        result = await AnalysisGraph(harness, Tools(), InMemorySaver()).graph.ainvoke(
            initial(), {"configurable": {"thread_id": "new-view"}})
        report = result["report"]["report_json"]
        assert result["output"]["report_id"] == "report"
        assert report["filing_facts"][0]["quote"] == FACT
        if reject is None:
            assert len(report["base"]["review_points"]) == 1
            markdown = report["sections"]["review_points"]
            assert "새로운 검토 관점" in markdown and "검토 조건" in markdown
            assert "기존 메모의 관점과 가정" not in markdown and "None" not in markdown
        else:
            assert report["base"]["review_points"] == []
            assert any("새 검토 관점" in warning for warning in report["warnings"])
        assert seen.count("base") == 1 and seen.count("report") == 1
        assert seen.count("output_check") == (0 if reject == "budget" else 1)
        assert ledger.row("task")["turns"] == (2 if reject == "budget" else 3)

    asyncio.run(check())


def test_mixed_views_survive_checkpoint_resume_and_lookup_failure(ledger):  # noqa: F811
    saver = InMemorySaver()
    config = {"configurable": {"thread_id": "resume-new"}}
    roles = []

    async def model(role, context, schema):
        roles.append(role)
        answer = await fake_model(role, context, schema)
        if role == "base":
            answer["review_points"] = [point(), point(
                view_type="MEMO_REVIEW", memo_view=MEMO, evidence=[MEMO_SOURCE, SOURCE],
                title="공장 건설 자금 일정의 반영 여부를 검토합니다.",
                question="대금 수취 지연이 기존 공장 자금계획에 반영되어 있습니까?")]
            answer["selected"] = [{"perspective_type": "FX_HEDGE", "selection_reason": "대금과 만기를 확인합니다.",
                                   "question": point()["question"]}]
        if role == "perspective":
            assert any(p["memo_view"] is None for p in context["review_points"])
            answer["status"] = "NEEDS_TOOLS"
            answer["requests"] = [{"tool": "local_search", "query": "달러 대금 환헤지 만기 금액"}]
        return answer

    async def check():
        harness = Harness("task", ledger, model)
        graph = AnalysisGraph(harness, Tools(), saver).graph
        await graph.ainvoke(initial(), {**config}, interrupt_before=["REPORT_AGENT"])
        checkpoint = await graph.aget_state(config)
        assert checkpoint.next == ("REPORT_AGENT",)
        assert len(checkpoint.values["base"]["review_points"]) == 2
        before = ledger.row("task")["turns"]
        result = await graph.ainvoke(None, config)
        assert {p["view_type"] for p in result["report"]["report_json"]["base"]["review_points"]} == {
            "MEMO_REVIEW", "DISCLOSURE_REVIEW"}
        assert roles.count("base") == 1
        assert ledger.row("task")["turns"] == before + 2

    asyncio.run(check())
