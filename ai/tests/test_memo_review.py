import asyncio

# ruff: noqa: F811
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from test_analysis import FakeTools, fake_model, initial, ledger  # noqa: F401

from disclosure_ai.harness.runtime import Harness
from disclosure_ai.workflow.graph import AnalysisGraph


@pytest.mark.parametrize("decision", ["KEEP", "HOLD", "INVALID_KEEP", "MEMO_ONLY_KEEP", "MISSING"])
@pytest.mark.parametrize("selected", [False, True])
def test_ir_announcement_and_empty_proposal_decision(ledger, decision, selected):
    body = "기업설명회(IR) 개최(안내공시)" + "\n일시 2026-10-29 14:00\n개최목적 2026년 3분기 경영실적 발표\nIR 자료는 실적발표일 공시로 갈음할 예정입니다."
    source = {"document_id": "filing:ir", "location": "line:1:overview", "quote": body}
    seen = []

    class Tools(FakeTools):
        async def call(self, name, args):
            self.calls.append(name)
            if name == "disclosure_get_document":
                return {"documents": [{"document_id": "filing:ir", "text": body}],
                        "changes": [], "complete_correction_table": False,
                        "report_name": "기업설명회(IR)개최(안내공시)", "metadata_status": "FOUND"}
            if name == "business_get_memo":
                return {"document_id": "memo:1", "text": "계약 취소가 있으면 잔존 선박의 인도와 회수 여부를 확인합니다.\n" * 100,
                        "version": 1}
            if name == "ensure_analysis_index":
                return {"indexed": True}
            if name == "search_evidence":
                return {"documents": [], "sources": []}
            if name == "business_save_report":
                return {"status": "COMPLETED", "report_id": "saved"}
            return {"error": "UNEXPECTED_TOOL"}

    async def model(role, context, schema):
        if role == "base":
            seen.append(context)
            assert context["analysis_type"] == "NEW"
            assert context["disclosure"]["title"] == "기업설명회(IR)개최(안내공시)"
            assert context["context"][0]["quote"] == " ".join(body.split())
            result = {"summary": "실적 발표 일정을 확인했습니다.", "proposals": [], "selected": [{"perspective_type": "FINANCE",
                        "selection_reason": "향후 Q&A를 확인합니다.", "question": "향후 실적은 무엇입니까?"}] if selected else [],
                      "no_additional_analysis_reason": "일정 안내로 확인된 신규 실적이나 계약 변경이 없습니다.",
                      "limitations": []}
            if decision != "MISSING":
                result["memo_review"] = {
                    "status": "KEEP" if decision in {"KEEP", "INVALID_KEEP", "MEMO_ONLY_KEEP"} else "HOLD",
                    "reason": "실적 발표 일정 안내이며 기존 메모의 수치를 변경할 사실은 발표되지 않았습니다."
                    if decision != "HOLD" else "현재 자료에서 기존 메모와의 연결 근거를 확인하지 못해 판단을 보류합니다.",
                    "evidence": ([{**source, "document_id": "invented"}] if decision == "INVALID_KEEP" else
                                 [{"document_id": "memo:1", "location": "line:1",
                                   "quote": "계약 취소가 있으면 잔존 선박의 인도와 회수 여부를 확인합니다."}]
                                 if decision == "MEMO_ONLY_KEEP" else [source]),
                }
            return result
        if role == "perspective":
            seen.append("perspective")
        return await fake_model(role, context, schema)

    async def check():
        tools = Tools()
        result = await AnalysisGraph(Harness("task", ledger, model), tools, InMemorySaver()).graph.ainvoke(
            initial(), {"configurable": {"thread_id": "ir"}}
        )
        data = result["report"]["report_json"]
        assert seen.count("perspective") == int(selected), result.get("warnings")
        assert "base" in result, result.get("warnings")
        assert bool(result["base"]["selected"]) is selected
        assert not data["base"]["proposals"]
        assert data["memo_review"]["status"] == ("KEEP" if decision == "KEEP" else "HOLD")
        assert data["memo_review"]["reason"]
        assert "기존 메모 유지" in result["report"]["content"] if decision == "KEEP" else "메모 영향 판단 보류" in result["report"]["content"]
        if decision == "KEEP":
            assert data["memo_review"]["evidence"] and "[근거 " in data["sections"]["suggestions"]
        assert tools.calls.count("ensure_analysis_index") == 1
        assert tools.calls.count("search_evidence") == 1

    asyncio.run(check())
