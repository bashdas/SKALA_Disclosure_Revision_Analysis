import asyncio

# ruff: noqa: F811
from langgraph.checkpoint.memory import InMemorySaver
from test_analysis import FakeTools, fake_model, filing, initial, ledger  # noqa: F401

from disclosure_ai.harness.output import safe_text
from disclosure_ai.harness.runtime import Harness
from disclosure_ai.services.business import RunCancelled
from disclosure_ai.services.documents import (
    analysis_context,
    model_context,
    reference_frames,
    validated_sources,
)
from disclosure_ai.workflow.graph import AnalysisGraph
from disclosure_ai.workflow.initial import impact
from disclosure_ai.workflow.perspectives import perspective
from disclosure_ai.workflow.reporting import compose, report


def test_target_review_survives_advisory_rejection_and_failure(ledger):
    text = "기존 목표주가 35,000원의 산정 전제 반영 여부를 확인해야 합니다."
    assert safe_text(text) == text
    assert safe_text("Review the existing target price assumptions.")
    assert not safe_text("지금 매수를 추천합니다.")

    async def check():
        async def model(role, context, schema):
            return {"safe_indices": []}

        h = Harness("task", ledger, model)
        payload = {"reason": text, "quote": "원문", "request": {"fixed": True}}
        checked, warnings = await h.review_output(payload, grounding=True, advisory=True)
        assert checked == payload and warnings
        ledger.db.execute("UPDATE runs SET turns=8 WHERE id='task'")
        ledger.db.commit()
        checked, warnings = await h.review_output(payload, grounding=True, advisory=True)
        assert checked == payload and warnings
        assert ledger.row("task")["turns"] == 8

    asyncio.run(check())


def test_advisory_still_propagates_cancellation(ledger):
    async def check():
        async def model(*args):
            raise RunCancelled("ANALYSIS_CANCELLED")

        try:
            await Harness("task", ledger, model).review_output(
                {"reason": "산정 근거를 확인합니다."}, advisory=True
            )
        except RunCancelled:
            return
        raise AssertionError("취소가 전파되어야 합니다.")

    asyncio.run(check())


def test_contract_change_without_formula_is_review_and_visible(ledger):
    async def model(role, context, schema):
        answer = await fake_model(role, context, schema)
        if role == "base":
            answer["proposals"] = [{
                "claim_id": "one", "impact_type": "CALCULATION_UPDATE",
                "before_text": "계약금액은 100입니다.", "after_text": "매출을 20 줄입니다.",
                "reason": "계약 총액 감소를 매출에서 차감합니다.",
                "evidence": [{k: v for k, v in filing()["changes"][0].items()
                              if k in {"document_id", "location", "quote", "url"}}],
                "calculation_basis": None,
            }]
        return answer

    async def check():
        h = Harness("task", ledger, model)
        run = AnalysisGraph(h, FakeTools(), InMemorySaver())
        memo = {"document_id": "memo:1:v1", "text": "계약금액은 100입니다."}
        state = {**initial(), "memo": memo, "filing": filing(),
                 "documents": filing()["documents"] + [memo], "context": filing()["changes"]}
        state.update(await impact(run, state))
        proposal = state["base"]["proposals"][0]
        assert proposal["impact_type"] == "INTERPRETATION_REVIEW"
        assert proposal["after_text"] is None
        state["base"]["limitations"] = ["기존 목표주가의 산정 근거 반영 여부를 확인해야 합니다."]
        result = await report(run, state)
        assert "금액 수정은 보류합니다" in result["report"]["content"]
        assert "기존 목표주가의 산정 근거 반영 여부" in result["report"]["content"]
        assert "매출을 20 줄입니다" not in result["report"]["content"]
        assert not state["base"]["selected"]

    asyncio.run(check())


def test_model_context_preserves_changes_and_valuation_rows():
    memo = {"document_id": "memo:1", "text":
            ("매출과 이익 " + "여백 " * 70 + "\n") * 100
            + "목표주가 산출\n적용 BPS 8,231원\n적용 P/B 4.3배\n목표주가 35,000원"}
    before = dict(memo)
    f = filing()
    context = f["changes"] + [{"document_id": "memo:1", "location": "memo", "quote": memo["text"]}]
    result = model_context(f, context, memo)
    assert "적용 BPS 8,231원" in result["memo"]["text"]
    assert "목표주가 35,000원" in result["memo"]["text"]
    assert result["context"][0]["before"] == "100"
    assert result["context"][0]["after"] == "80"
    assert memo == before


def test_short_memo_quote_keeps_its_line_and_scope():
    text = "BPS 전망 9,999원\n적용 BPS(원) 7,777 2028 BPS\nTarget P/B(배) 4.1"
    memo = {"document_id": "memo:scope", "text": text}
    quote = "적용 BPS(원) 7,777 2028 BPS"
    source = {"document_id": memo["document_id"], "location": "memo", "quote": quote}
    full = {"document_id": memo["document_id"], "location": "memo", "quote": text}
    checked = validated_sources([source], [memo], [full])
    assert checked[0]["quote"] == quote
    assert checked[0]["location"] == "line:2"
    assert "9,999" not in checked[0]["quote"]
    assert full["quote"] == text


def test_reference_frames_bind_values_to_applied_rows_and_contract_scope():
    memo = {"document_id": "memo:scope", "text":
            "BPS 전망 9,999원\n적용 BPS(원) 7,777 2028 BPS\nTarget P/B(배) 4.1"}
    changes = [
        {"label": "체결계약명", "before": "선박 4척", "after": "선박 3척",
         "document_id": "filing:scope", "location": "table:0:row:1", "quote": "선박 4척 3척"},
        {"label": "계약금액", "before": "900", "after": "650",
         "document_id": "filing:scope", "location": "table:0:row:2", "quote": "계약금액 900 650"},
        {"label": "계약명", "before": "별도 공사", "after": "별도 공사 정정",
         "document_id": "filing:scope", "location": "table:1:row:1", "quote": "별도 공사"},
    ]
    frames = reference_frames({"changes": changes}, memo)
    rows = frames["applied_valuation_rows"]
    assert [row["location"] for row in rows] == ["line:2", "line:3"]
    assert "7,777" in rows[0]["quote"] and "9,999" not in str(rows)
    scope = frames["contract_amount_scopes"][0]
    assert scope["before_contract_total"] == {"scope": "선박 4척", "amount": "900"}
    assert scope["after_contract_total"] == {"scope": "선박 3척", "amount": "650"}
    assert scope["same_scope"] is False
    assert len(scope["sources"]) == 2

    context = analysis_context({"changes": changes}, changes)
    amount = context[1]
    assert amount["before_scope"] == "선박 4척"
    assert amount["after_scope"] == "선박 3척"
    assert amount["comparison_basis"] == "CONTRACT_TOTAL_DIFFERENT_SCOPE"


def test_partial_perspective_is_visible_and_insufficient_requests_are_executed(ledger):
    source = {k: v for k, v in filing()["changes"][0].items()
              if k in {"document_id", "location", "quote", "url"}}
    answer = {"status": "INSUFFICIENT_EVIDENCE",
              "findings": "계약금액이 변경된 사실을 확인했습니다. 정량 영향은 판단을 보류합니다.",
              "sources": [source], "requests": [], "limitations": ["회계 반영액은 미확인입니다."]}

    async def model(role, context, schema):
        return answer if role == "perspective" else await fake_model(role, context, schema)

    async def check():
        run = AnalysisGraph(Harness("task", ledger, model), FakeTools(), InMemorySaver())
        selection = {"perspective_type": "FINANCE", "selection_reason": "재무 영향을 확인합니다.",
                     "question": "정량 영향은 무엇입니까?"}
        state = {**initial(), "selection": selection, "base": {"selected": [selection]},
                 "filing": filing(), "documents": filing()["documents"],
                 "context": filing()["changes"]}
        update = await perspective(run, state)
        result = update["results"]["FINANCE"]
        assert result["status"] == "COMPLETED" and result["findings"] == answer["findings"]
        state.update(update)
        generated = await report(run, state)
        assert answer["findings"].split(" ")[0] in generated["report"]["content"]
        assert "추가 확인 항목 있음" in generated["report"]["content"]
        answer["sources"] = [{**source, "document_id": "unknown"}]
        state.pop("jobs")
        rejected = await perspective(run, state)
        assert rejected["results"]["FINANCE"]["status"] == "INSUFFICIENT_EVIDENCE"
        assert not rejected["results"]["FINANCE"]["findings"]
        answer["sources"] = [source]
        answer["requests"] = [{"tool": "local_search", "query": "회계 반영액"}]
        queued = await perspective(run, state)
        assert queued["jobs"]["FINANCE"]["status"] == "NEEDS_TOOLS"
        assert queued["jobs"]["FINANCE"]["requests"]

    asyncio.run(check())


def test_unchanged_proposals_keep_text_and_citations():
    source = {"document_id": "filing:1", "location": "line:1", "quote": "계약 변경"}
    before = "기존 산정 전제를 유지합니다."
    for after, impact_type in [(before, "INTERPRETATION_REVIEW"),
                               ("기존  산정 전제를 유지합니다.\n", "FACT_UPDATE"),
                               (None, "NO_IMPACT"),
                               ("새 산정 전제를 검토합니다.", "INTERPRETATION_REVIEW")]:
        proposal = {"before_text": before, "after_text": after, "impact_type": impact_type,
                    "reason": "공시와 메모를 대조했습니다.", "evidence": [source]}
        data = {"request": {"company_name_snapshot": "기업", "disclosure_receipt_no": "1"},
                "base": {"proposals": [proposal]}}
        result = compose(data)
        section = result["report_json"]["sections"]["suggestions"]
        assert "[근거 1]" in section and source in result["report_json"]["sources"]
        if after == "새 산정 전제를 검토합니다.":
            assert "수정 제안 1" in section and "수정: 새 산정 전제" in section
        else:
            assert "유지 제안 1" in section and "유지: " + before in section
            assert "수정:" not in section
