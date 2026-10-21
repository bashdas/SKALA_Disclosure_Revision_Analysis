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
        return value

    async def check():
        graph = AnalysisGraph(Harness("task", ledger, model), FakeTools(), InMemorySaver()).graph
        state = await graph.ainvoke(initial(), {"configurable": {"thread_id": "gate"}})
        body = state["report"]
        assert "UNSUPPORTED" not in json.dumps(body)
        assert "report" not in calls
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
            "safe_indices": [i for i, row in enumerate(rows) if row["evidence"][0]["quote"] == fact]
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
    assert "재무 수치와 메모의 연결 여부" in body["content"]
    assert body["report_json"]["results"]["FINANCE"]["findings"] == ""
