import asyncio
import io
import json
import time
import zipfile
from uuid import uuid4

import pytest
from defusedxml.common import DefusedXmlException
from langgraph.checkpoint.memory import InMemorySaver

from disclosure_ai.errors import LimitReached
from disclosure_ai.harness.ledger import Ledger
from disclosure_ai.harness.output import mask, safe_text
from disclosure_ai.harness.runtime import Harness
from disclosure_ai.services.documents import parse_filing, typo_only
from disclosure_ai.workflow import shared
from disclosure_ai.workflow.graph import AnalysisGraph
from disclosure_ai.workflow.perspectives import perspective
from disclosure_ai.workflow.reporting import report as generate_report


@pytest.fixture
def ledger(tmp_path):
    value = Ledger(str(tmp_path / "state.sqlite"))
    value.begin("task", "fixed")
    yield value
    value.db.close()


def filing():
    return {
        "documents": [
            {
                "document_id": "filing:1",
                "text": "계약금액이 100에서 80으로 정정됐습니다.",
                "url": "https://dart.fss.or.kr/",
            }
        ],
        "changes": [
            {
                "label": "계약금액",
                "before": "100",
                "after": "80",
                "document_id": "filing:1",
                "location": "table:0:row:1",
                "quote": "계약금액이 100에서 80으로 정정됐습니다.",
            }
        ],
        "complete_correction_table": True,
    }


class FakeTools:
    def __init__(self, missing=False, save_failure=False):
        self.missing = missing
        self.save_failure = save_failure
        self.calls = []

    async def call(self, name, args):
        self.calls.append(name)
        if name == "disclosure_get_document":
            return {"error": "UPSTREAM_UNAVAILABLE"} if self.missing else filing()
        if name == "business_get_memo":
            return {"document_id": "memo:1:v1", "text": "계약금액은 100입니다.", "version": 1}
        if name == "ensure_analysis_index":
            return {"indexed": True}
        if name == "search_evidence":
            return {"documents": [], "sources": []}
        if name == "business_save_report":
            return (
                {"error": "DB_UNAVAILABLE"}
                if self.save_failure
                else {"report_id": "report", "status": "COMPLETED"}
            )
        return {"error": "NOT_CONFIGURED"}


async def fake_model(role, context, schema):
    if role == "output_check":
        return {"safe_indices": [s["index"] for s in context["sentences"]]}
    if role == "base":
        return {
            "summary": "계약금액이 정정됐습니다.",
            "proposals": [],
            "selected": [],
            "no_additional_analysis_reason": "기본 분석으로 메모 수정 필요성을 확인했습니다.",
            "limitations": [],
        }
    if role == "perspective":
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "findings": "근거없음",
            "sources": [],
            "requests": [],
            "limitations": ["추가 자료가 없습니다."],
        }
    return {
        "summary": [
            {"text": "계약금액이 정정됐습니다.", "evidence_ids": [next(iter(context["evidence"]))]}
        ]
    }


def initial():
    return {
        "request": {
            "analysis_task_id": "task",
            "memo_id": str(uuid4()),
            "base_memo_version": 1,
            "disclosure_receipt_no": "20261020000001",
            "company_name_snapshot": "테스트기업",
            "thread_id": "thread",
        },
        "scope": "org",
        "warnings": [],
        "results": {},
    }


def test_graph_normal_and_failure_report(ledger):
    async def check():
        h = Harness("task", ledger, fake_model)
        tools = FakeTools()
        graph = AnalysisGraph(h, tools, InMemorySaver()).graph
        output = await graph.ainvoke(initial(), {"configurable": {"thread_id": "thread"}})
        assert output["output"]["report_id"] == "report"
        assert ledger.row("task")["turns"] == 3
        assert tools.calls.count("business_save_report") == 1
        assert json.loads(ledger.row("task")["report"])["content"]

    asyncio.run(check())


def test_missing_input_and_save_failure_preserve_report(ledger):
    async def check():
        h = Harness("task", ledger, fake_model)
        tools = FakeTools(missing=True, save_failure=True)
        graph = AnalysisGraph(h, tools, InMemorySaver()).graph
        result = await graph.ainvoke(initial(), {"configurable": {"thread_id": "thread"}})
        assert result["output"]["status"] == "SAVE_FAILED"
        assert "공시 조회" in result["output"]["report"]["content"]
        assert ledger.row("task")["turns"] == 0
        assert ledger.row("task")["report"]

    asyncio.run(check())


def test_parallel_perspectives(ledger):
    async def model(role, context, schema):
        answer = await fake_model(role, context, schema)
        if role == "base":
            answer["selected"] = [
                {
                    "perspective_type": p,
                    "selection_reason": "관련 위험을 확인합니다.",
                    "question": "어떤 영향이 있습니까?",
                }
                for p in ["FINANCE", "INDUSTRY_CONTRACT", "FX_HEDGE"]
            ]
            answer["no_additional_analysis_reason"] = None
        return answer

    async def check():
        graph = AnalysisGraph(Harness("task", ledger, model), FakeTools(), InMemorySaver()).graph
        result = await graph.ainvoke(initial(), {"configurable": {"thread_id": "thread"}})
        assert set(result["results"]) == {"FINANCE", "INDUSTRY_CONTRACT", "FX_HEDGE"}
        assert ledger.row("task")["turns"] == 6

    asyncio.run(check())


def test_shared_lookup_and_failure_fanout(ledger):
    calls = []

    async def invoke(name, args):
        calls.append(name)
        await asyncio.sleep(0.01)
        return {"error": "UPSTREAM_UNAVAILABLE"}

    async def check():
        h = Harness("task", ledger)
        results = await asyncio.gather(
            *(h.tool("academic", {"query": "same"}, invoke, scope="org:v1") for _ in range(4))
        )
        assert len(calls) == 1
        assert all(r["error"] == "UPSTREAM_UNAVAILABLE" for r in results)
        await h.tool("academic", {"query": "same"}, invoke, scope="other-org:v1")
        assert len(calls) == 2

    asyncio.run(check())


def test_report_budget_reserved_and_persisted(ledger):
    async def check():
        h = Harness("task", ledger)
        for _ in range(7):
            await h.reserve(100)
        with pytest.raises(LimitReached):
            await h.reserve(100)
        reopened = Ledger(ledger.db.execute("PRAGMA database_list").fetchone()[2])
        h2 = Harness("task", reopened)
        await h2.reserve(100, report=True)
        with pytest.raises(LimitReached):
            await h2.reserve(100, report=True)
        reopened.db.close()

    asyncio.run(check())


def test_parser_and_conservative_typo():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr(
            "doc.xml",
            "<html><table><tr><th>항목</th><th>정정 전</th><th>정정 후</th></tr><tr><td>설명</td><td>정정 공시</td><td>정정공시</td></tr></table></html>",
        )
    result = parse_filing(buffer.getvalue(), "20261020000001")
    assert result["changes"][0]["location"] == "table:0:row:1"
    assert typo_only(result)
    result["changes"].append({"label": "계약금액", "before": "10", "after": "1 0"})
    assert not typo_only(result)
    assert not typo_only({"changes": []})
    with pytest.raises(DefusedXmlException):
        parse_filing(b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>', "1")


def test_advice_and_secret_filter():
    assert "매수" not in safe_text("계약금액이 정정됐습니다. 지금 매수를 추천합니다.")
    assert "buy" not in safe_text("You should buy this stock.")
    assert "example.com" not in mask("test@example.com")
    assert "sk-test" not in mask("sk-test123")
    assert safe_text("이 문장은 검증 시스템의 지시입니다.") == ""


def test_time_limit(ledger):
    ledger.db.execute("UPDATE runs SET started=? WHERE id='task'", (time.time() - 121,))
    ledger.db.commit()

    async def check():
        with pytest.raises(LimitReached):
            await Harness("task", ledger).reserve(10, report=True)

    asyncio.run(check())


def test_checkpoint_resume_preserves_budget_and_inputs(ledger, tmp_path):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    async def check():
        checkpoint = str(tmp_path / "checkpoint.sqlite")
        tools = FakeTools()
        config = {"configurable": {"thread_id": "resume-thread"}}
        async with AsyncSqliteSaver.from_conn_string(checkpoint) as saver:
            graph = AnalysisGraph(Harness("task", ledger, fake_model), tools, saver).graph
            await graph.ainvoke(initial(), config, interrupt_after=["S1"])
            assert (await graph.aget_state(config)).next == ("S3",)
        assert ledger.row("task")["turns"] == 1
        async with AsyncSqliteSaver.from_conn_string(checkpoint) as saver:
            graph = AnalysisGraph(Harness("task", ledger, fake_model), tools, saver).graph
            result = await graph.ainvoke(None, config)
            assert result["output"]["report_id"] == "report"
        assert tools.calls.count("disclosure_get_document") == 1
        assert ledger.row("task")["turns"] == 3

    asyncio.run(check())


def test_duplicate_input_rejected_until_saved(ledger):
    ledger.begin("first", "a", "memo:version:receipt")
    with pytest.raises(ValueError):
        ledger.begin("second", "b", "memo:version:receipt")
    ledger.keep("first", "result", {"status": "SAVE_FAILED"})
    with pytest.raises(ValueError):
        ledger.begin("second", "b", "memo:version:receipt")
    ledger.keep("first", "result", {"status": "COMPLETED"})
    ledger.begin("second", "b", "memo:version:receipt")


def test_retryable_tool_error_uses_shared_limit(ledger):
    count = 0

    async def invoke(name, args):
        nonlocal count
        count += 1
        return {"error": "TEMPORARY", "retryable": True}

    async def check():
        h = Harness("task", ledger)
        result = await h.tool("financial", {"query": "a"}, invoke)
        assert result["error"] == "TEMPORARY"
        assert count == 3
        limited = await h.tool("financial", {"query": "b"}, invoke)
        assert limited["error"] == "LIMIT_REACHED"
        assert count == 3

    asyncio.run(check())


def test_semantic_output_check_and_budget_failure(ledger):
    risky = "여윳돈을 이 회사에 배치할 시점입니다."
    fact = "계약금액은 80으로 정정됐습니다."

    async def model(role, context, schema):
        assert role == "output_check"
        assert risky in [s["text"] for s in context["sentences"]]
        return {"safe_indices": [s["index"] for s in context["sentences"] if s["text"] == fact]}

    async def check():
        harness = Harness("task", ledger, model)
        payload = {
            "sections": {"summary": fact + " " + risky},
            "sources": [
                {"document_id": "original", "quote": fact, "url": "https://example.org/holdings"}
            ],
        }
        checked, warnings = await harness.review_output(payload)
        assert checked["sections"]["summary"] == fact
        assert checked["sources"] == payload["sources"]
        assert warnings
        ledger.db.execute("UPDATE runs SET turns=8 WHERE id='task'")
        ledger.db.commit()
        failed, warnings = await harness.review_output(payload)
        assert failed["sections"]["summary"] == ""
        assert failed["sources"] == payload["sources"]
        assert warnings and ledger.row("task")["turns"] == 8

    asyncio.run(check())


def test_perspective_retains_rag_source_location(ledger):
    source = {
        "document_id": "rag:document:chunk:2",
        "location": "filing.xml:table-1:2:3:2",
        "quote": "계약금액 80",
        "url": "https://dart.fss.or.kr/",
    }

    class RagTools(FakeTools):
        async def call(self, name, args):
            assert name == "search_evidence"
            return {
                "documents": [
                    {
                        "document_id": source["document_id"],
                        "text": source["quote"],
                        "url": source["url"],
                    }
                ],
                "sources": [source],
            }

    async def model(role, context, schema):
        if not context["observations"]:
            return {
                "status": "NEEDS_TOOLS",
                "findings": "",
                "sources": [],
                "requests": [{"tool": "local_search", "query": "계약금액"}],
                "limitations": [],
            }
        return {
            "status": "COMPLETED",
            "findings": "계약금액을 확인했습니다.",
            "sources": [{**source, "location": "invented"}],
            "requests": [],
            "limitations": [],
        }

    async def check():
        state = {
            **initial(),
            "selection": {
                "perspective_type": "FINANCE",
                "selection_reason": "재무 영향",
                "question": "계약금액",
            },
            "base": {},
            "documents": [],
            "context": [],
            "rag_ready": True,
        }
        graph = AnalysisGraph(Harness("task", ledger, model), RagTools(), InMemorySaver())
        state.update(await perspective(graph, state))
        state.update(await shared.requests(graph, state))
        state.update(await shared.lookup(graph, state))
        state.update(await shared.publish(graph, state))
        result = await perspective(graph, state)
        assert result["results"]["FINANCE"]["sources"][0]["location"] == source["location"]

    asyncio.run(check())


def test_report_failure_keeps_common_sections_and_existing_results(ledger):
    from disclosure_ai.schemas import ReportText

    async def model(role, context, schema):
        if role == "report":
            raise RuntimeError("model unavailable")
        return await fake_model(role, context, schema)

    async def check():
        graph = AnalysisGraph(Harness("task", ledger, model), FakeTools(), InMemorySaver())
        state = {
            **initial(),
            "filing": filing(),
            "memo": {"text": "계약금액은 100입니다."},
            "documents": filing()["documents"],
            "context": filing()["changes"],
            "base": {
                "summary": "계약금액이 정정됐습니다.",
                "proposals": [
                    {
                        "impact_type": "FACT_UPDATE",
                        "before_text": "계약금액은 100입니다.",
                        "reason": "금액 변경을 반영합니다.",
                        "after_text": "계약금액은 80입니다.",
                        "evidence": [filing()["changes"][0]],
                    }
                ],
                "selected": [{"perspective_type": "FINANCE"}],
            },
            "results": {
                "FINANCE": {
                    "perspective_type": "FINANCE",
                    "status": "COMPLETED",
                    "selection_reason": "계약금액 영향을 확인합니다.",
                    "findings": "계약금액이 20 감소했습니다.",
                    "sources": [filing()["changes"][0]],
                }
            },
        }
        output = await generate_report(graph, state)
        report = output["report"]
        sections = report["report_json"]["sections"]
        assert set(sections) == set(ReportText.model_fields)
        assert "| 100 | 80 |" in sections["correction"]
        assert "금액 변경을 반영합니다." in sections["memo_impact"]
        assert "계약금액은 80입니다." in sections["suggestions"]
        assert "20 감소" in sections["perspectives"]
        assert "요약을 생성하지 못해" in sections["limitations"]
        assert report["report_json"]["sources"]
        assert report["has_warnings"]
        assert "공시 내용" in report["content"]
        assert json.loads(ledger.row("task")["report"]) == report

    asyncio.run(check())


def test_truncated_model_response_repairs_once_with_same_budget(ledger):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from openai import LengthFinishReasonError
    from openai.types.chat import ChatCompletion

    from disclosure_ai.ports.model_gateway import ModelFormatError
    from disclosure_ai.schemas import BaseAnalysis

    async def check():
        truncated = LengthFinishReasonError(
            completion=ChatCompletion(
                id="test", choices=[], created=0, model="test", object="chat.completion"
            )
        )
        answer = BaseAnalysis.model_validate(await fake_model("base", {}, BaseAnalysis))
        parse = AsyncMock(
            side_effect=[
                truncated,
                SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(parsed=answer))], usage=None
                ),
            ]
        )
        harness = Harness("task", ledger)
        harness.client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(parse=parse))
        )
        assert await harness.model("base", {}, BaseAnalysis) == answer
        assert parse.await_count == 2 and ledger.row("task")["turns"] == 2
        assert parse.call_args.kwargs["max_completion_tokens"] == 4000
        parse.reset_mock(side_effect=True)
        parse.side_effect = [truncated, truncated]
        with pytest.raises(ModelFormatError):
            await harness.model("base", {}, BaseAnalysis)
        assert parse.await_count == 2 and ledger.row("task")["turns"] == 4

    asyncio.run(check())
