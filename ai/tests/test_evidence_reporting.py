import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from langgraph.checkpoint.memory import InMemorySaver
from test_analysis import FakeTools, fake_model, filing, initial, ledger  # noqa: F401

from disclosure_ai.harness.runtime import Harness
from disclosure_ai.schemas import BaseAnalysis
from disclosure_ai.services.documents import normalize_evidence, validated_sources
from disclosure_ai.workflow.graph import AnalysisGraph


def test_unfounded_proposals_and_findings_never_reach_report(ledger):  # noqa: F811
    calls = []

    async def model(role, context, schema):
        calls.append(role)
        assert "UNSUPPORTED" not in json.dumps(context)
        value = await fake_model(role, context, schema)
        if role == "base":
            value["proposals"] = [
                {
                    "claim_id": "bad",
                    "impact_type": "FACT_UPDATE",
                    "before_text": "",
                    "after_text": "UNSUPPORTED",
                    "reason": "UNSUPPORTED",
                    "evidence": [
                        {
                            k: v
                            for k, v in filing()["changes"][0].items()
                            if k in {"document_id", "location", "quote"}
                        }
                    ],
                }
            ]
            value["selected"] = [
                {
                    "perspective_type": "FINANCE",
                    "selection_reason": "계약금액 변경의 재무 영향을 확인합니다.",
                    "question": "재무 영향은 무엇입니까?",
                }
            ]
        if role == "perspective":
            value["findings"] = "UNSUPPORTED"
        if role == "base" and "selected" in value:
            value["not_selected"] = [{"perspective_type": kind, "reason": "기본 분석으로 충분합니다."}
                for kind in ["INDUSTRY_CONTRACT", "FINANCE", "FX_HEDGE", "MARKET_NEWS"]
                if kind not in {s["perspective_type"] for s in value["selected"]}]
        return value

    async def check():
        graph = AnalysisGraph(Harness("task", ledger, model), FakeTools(), InMemorySaver()).graph
        state = await graph.ainvoke(initial(), {"configurable": {"thread_id": "gate"}})
        body = state["report"]
        assert "UNSUPPORTED" not in json.dumps(body)
        assert "report" in calls
        assert body["report_json"]["base"]["proposals"] == []
        assert body["report_json"]["sections"]["perspectives"] == ""
        assert "계약금액 변경의 재무 영향을 확인합니다." in body["content"]
        assert "근거 부족으로 미작성" in body["content"]

    asyncio.run(check())


def test_same_sentence_is_checked_against_its_own_evidence(ledger):  # noqa: F811
    fact = "계약금액은 80입니다."

    async def model(role, context, schema):
        assert context["require_grounding"]
        rows = context["sentences"]
        assert len(rows) == 2
        return {
            "safe_indices": [
                i
                for i, row in enumerate(rows)
                if context["evidence"][row["evidence_ids"][0]]["quote"] == fact
            ]
        }

    async def check():
        payload = {
            "claims": [
                {"text": fact, "evidence": [{"document_id": "a", "quote": quote}]}
                for quote in (fact, "계약금액은 100입니다.")
            ]
        }
        checked, warnings = await Harness("task", ledger, model).review_output(
            payload, grounding=True
        )
        assert [row["text"] for row in checked["claims"]] == [fact, ""]
        assert warnings

    asyncio.run(check())


def test_financial_cutoff_identity_and_raw_amount():
    args = {
        "corp_code": "00126380",
        "bsns_year": 2025,
        "reprt_code": "11011",
        "fs_div": "CFS",
        "as_of": "2026-10-20",
    }
    result = {
        **args,
        "accounts": [
            {
                "rcept_no": "20260301000001",
                "account_nm": "매출액",
                "thstrm_amount": "1,234,567,890,123,456,789",
            }
        ],
        "sources": [
            {
                "identifier": "20260301000001",
                "published_at": "2026-03-01",
                "original_location": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260301000001",
            }
        ],
    }
    normalized = normalize_evidence(result, "financial", args)
    assert "1,234,567,890,123,456,789" in normalized["documents"][0]["text"]
    for date in (None, "2026-10-21"):
        result["sources"][0]["published_at"] = date
        assert not normalize_evidence(result, "financial", args)["sources"]
    assert normalize_evidence({**result, "corp_code": "99999999"}, "financial", args)["error"]
    assert set(
        validated_sources(filing()["changes"], filing()["documents"], filing()["changes"])[0]
    ) == {"document_id", "location", "quote", "url", "published_at"}
    assert validated_sources([{"quote": "bad"}], filing()["documents"], filing()["changes"]) == []


def test_long_model_input_stays_valid_json(ledger):  # noqa: F811
    async def parse(**kwargs):
        context = json.loads(kwargs["messages"][1]["content"])
        assert context["context_truncated"] is True
        assert context["memo"]["text"] == "계약금액은 100입니다."
        answer = BaseAnalysis.model_validate(await fake_model("base", {}, BaseAnalysis))
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=answer))], usage=None
        )

    async def check():
        h = Harness("task", ledger)
        h.client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(parse=AsyncMock(side_effect=parse)))
        )
        await h.model(
            "base",
            {
                "memo": {"text": "계약금액은 100입니다."},
                "context": [{"quote": "긴 공시 본문 " * 2000} for _ in range(20)],
            },
            BaseAnalysis,
        )
        assert h.client.chat.completions.parse.await_count == 1

    asyncio.run(check())


def test_emergency_preserves_selected_perspective_without_unchecked_findings(ledger):  # noqa: F811
    from disclosure_ai.workflow.reporting import emergency

    state = initial()
    state["base"] = {
        "selected": [{"perspective_type": "FINANCE", "selection_reason": "UNSUPPORTED"}]
    }
    state["results"] = {"FINANCE": {"status": "COMPLETED", "findings": "UNSUPPORTED"}}
    body = emergency(SimpleNamespace(h=Harness("task", ledger)), state, TimeoutError())
    assert "UNSUPPORTED" not in json.dumps(body)
    assert "이 관점의 판단 이유가 저장되지 않았습니다." in body["content"]
    assert body["report_json"]["results"]["FINANCE"]["findings"] == ""


def test_merged_correction_cells_preserve_all_rows():
    from disclosure_ai.services.documents import correction_rows

    def cell(text, rowspan=1, colspan=1):
        return {"text": text, "rowspan": rowspan, "colspan": colspan}

    rows = [
        {"cells": [cell("항목"), cell("정정사유"), cell("정정 전"), cell("정정 후")]},
        {"cells": [cell("ESG", 2), cell("연례갱신", 2), cell("97.32%"), cell("98.36%")]},
        {"cells": [cell("Microsoft"), cell("Siemens")]},
    ]
    changes, complete = correction_rows(rows)
    assert complete and len(changes) == 2
    assert changes[1][1]["label"] == "ESG" and changes[1][1]["after"] == "Siemens"
    assert correction_rows([{"cells": [cell("본문 제목", colspan=3)]}]) == ([], True)
    rows[1]["cells"][0]["rowspan"] = 1000000
    assert correction_rows(rows)[1] is False


def test_future_impact_keeps_conditions_and_uses_deduplicated_evidence(ledger):  # noqa: F811
    from disclosure_ai.harness.output import safe_text

    assert safe_text("보유 자산의 ESG 비율은 98.36%입니다.")
    scenario = "계약금액 감소가 매출에 반영되는 경우 해당 계약의 매출 기여가 줄어들 수 있습니다."
    source = {"document_id": "a", "quote": "계약금액이 100에서 80으로 정정됐습니다."}

    async def model(role, context, schema):
        assert len(context["evidence"]) == 1
        rows = context["sentences"]
        assert any(row["kind"] == "scenario" and row["text"] == scenario for row in rows)
        return {"safe_indices": [row["index"] for row in rows if row["kind"] == "scenario"]}

    async def check():
        payload = {
            "future_impacts": [{"scenario": scenario, "evidence": [source]}],
            "summary_claims": [{"text": "이익은 반드시 늘어납니다.", "evidence": [source]}],
        }
        checked, _ = await Harness("task", ledger, model).review_output(payload, grounding=True)
        assert checked["future_impacts"][0]["scenario"] == scenario
        assert checked["summary_claims"][0]["text"] == ""

    asyncio.run(check())


def test_quote_whitespace_is_restored_without_changing_numbers():
    quote = "ESG\n\n비율은\n98.36%입니다."
    source = {"document_id": "doc", "location": "row:4", "quote": quote}
    docs = [{"document_id": "doc", "text": quote}]
    candidate = {**source, "quote": "ESG 비율은 98.36%입니다."}
    assert validated_sources([candidate], docs, [source])[0]["quote"] == quote
    assert not validated_sources(
        [{**candidate, "quote": "ESG 비율은 99.36%입니다."}], docs, [source]
    )


def test_source_reference_resolves_only_one_known_location():
    source = {"document_id": "doc", "location": "row:4", "quote": "금액은 80입니다."}
    docs = [{"document_id": "doc", "text": source["quote"]}]
    reference = {**source, "quote": ""}
    assert validated_sources([reference], docs, [source])[0]["quote"] == source["quote"]
    assert not validated_sources([{**reference, "location": "row:5"}], docs, [source])
    assert not validated_sources(
        [reference], docs, [source, {**source, "quote": "금액은 90입니다."}]
    )


def test_model_context_preserves_explicit_before_and_after():
    from disclosure_ai.services.documents import analysis_context

    data = filing()
    original = data["changes"][0].copy()
    context = analysis_context(data, data["changes"])
    assert context[0]["before"] == "100" and context[0]["after"] == "80"
    assert "quote" not in context[0] and data["changes"][0] == original


def test_review_preserves_numbered_headings_and_correction_columns(ledger):  # noqa: F811
    source = {
        "document_id": "doc",
        "location": "row:6",
        "quote": "제 4 부 1. 재무내용 2024.12.31 2025.12.31",
    }
    claim = "제 4 부 1. 재무내용의 기준일이 2025년으로 변경되었습니다."

    async def model(role, context, schema):
        assert len(context["sentences"]) == 1
        assert context["sentences"][0]["text"] == claim
        assert context["evidence"]["E1"]["correction"]["after"] == "2025.12.31"
        return {"safe_indices": [0]}

    async def check():
        checked, warnings = await Harness("task", ledger, model).review_output(
            {"reason": claim, "evidence": [source]},
            grounding=True,
            corrections=[
                {
                    "label": "재무내용",
                    "before": "2024.12.31",
                    "after": "2025.12.31",
                    "source": source,
                }
            ],
        )
        assert checked["reason"] == claim and not warnings

    asyncio.run(check())
