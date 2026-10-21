# ruff: noqa: F811
import asyncio
import hashlib
import json
import time
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from test_analysis import FakeTools, fake_model, initial, ledger  # noqa: F401

from disclosure_ai.harness.lookup import normalize
from disclosure_ai.harness.runtime import Harness
from disclosure_ai.harness.transport import bind
from disclosure_ai.services.business import RunCancelled, internal_request
from disclosure_ai.workflow.execution import execute, retry_save
from disclosure_ai.workflow.graph import AnalysisGraph


def test_shared_stage_roundtrip_and_checkpoint_resume(ledger, tmp_path):
    calls = []
    source = {
        "document_id": "rag:shared",
        "quote": "매출은 80입니다.",
        "location": "table:1",
        "url": "https://example.test/filing",
    }

    class Tools(FakeTools):
        async def call(self, name, args):
            if name == "search_evidence":
                self.calls.append((name, args["query"]))
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
            return await super().call(name, args)

    async def model(role, context, schema):
        calls.append(role)
        result = await fake_model(role, context, schema)
        if role == "base":
            result["selected"] = [
                {
                    "perspective_type": kind,
                    "selection_reason": "정정 영향 확인",
                    "question": "매출 변화",
                }
                for kind in ["FINANCE", "INDUSTRY_CONTRACT"]
            ]
        if role == "perspective":
            if not context["observations"]:
                query = (
                    "매출   근거"
                    if context["selection"]["perspective_type"] == "FINANCE"
                    else "매출 근거"
                )
                return {
                    "status": "NEEDS_TOOLS",
                    "findings": "",
                    "sources": [],
                    "requests": [{"tool": "local_search", "query": query}],
                    "limitations": [],
                }
            return {
                "status": "COMPLETED",
                "findings": "매출을 확인했습니다.",
                "sources": [source],
                "requests": [],
                "limitations": [],
            }
        return result

    async def check():
        tools = Tools()
        config = {"configurable": {"thread_id": "shared-resume"}, "recursion_limit": 40}
        checkpoint = str(tmp_path / "checkpoints.sqlite")
        async with AsyncSqliteSaver.from_conn_string(checkpoint) as saver:
            graph = AnalysisGraph(Harness("task", ledger, model), tools, saver).graph
            await graph.ainvoke(initial(), config, interrupt_after=["S2"])
            snapshot = await graph.aget_state(config)
            assert snapshot.next == ("S3",)
            assert all(job["status"] == "NEEDS_TOOLS" for job in snapshot.values["jobs"].values())
        assert calls == ["base", "perspective", "perspective"]
        async with AsyncSqliteSaver.from_conn_string(checkpoint) as saver:
            graph = AnalysisGraph(Harness("task", ledger, model), tools, saver).graph
            final = await graph.ainvoke(None, config)
        assert all(item["status"] == "COMPLETED" for item in final["results"].values())
        assert tools.calls.count(("search_evidence", "매출 근거")) == 1
        assert calls.count("base") == 1 and calls.count("perspective") == 4
        assert final["output"]["report_id"] == "report"
        assert (
            ledger.db.execute(
                "SELECT count(*) FROM source_bodies WHERE text=?", (source["quote"],)
            ).fetchone()[0]
            == 1
        )
        counts = json.loads(ledger.row("task")["tools"])
        assert counts["search_evidence"] == 2
        assert ledger.row("task")["turns"] == 7

    asyncio.run(check())


def test_inflight_restart_preserves_budget_and_cache_scope(ledger):
    args = {"query": "재무  자료", "as_of": "2026-10-20"}
    normalized = normalize(args)
    key = hashlib.sha256(
        json.dumps(["org-a", "financial", normalized], sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    ledger.lookup_state("task", key, "financial", "RUNNING", 1)
    ledger.db.execute("UPDATE runs SET tools=? WHERE id='task'", (json.dumps({"financial": 1}),))
    ledger.db.commit()
    calls = []

    async def invoke(name, received):
        calls.append(received)
        return {
            "documents": [
                {
                    "document_id": "doc",
                    "text": "원문입니다.",
                    "url": "https://example.test/filing?a=1&b=2",
                }
            ]
        }

    async def check():
        h = Harness("task", ledger)
        first = await h.tool("financial", args, invoke, scope="org-a")
        again = await h.tool(
            "financial", {"query": "재무 자료", "as_of": "20261020"}, invoke, scope="org-a"
        )
        assert first == again and len(calls) == 1
        assert json.loads(ledger.row("task")["tools"])["financial"] == 2
        await h.tool("financial", args, invoke, scope="org-b")
        assert len(calls) == 2
        assert ledger.db.execute("SELECT count(*) FROM source_bodies").fetchone()[0] == 2
        assert any(e["kind"] == "LOOKUP_RECOVERED" for e in ledger.events("task"))

        async def denied(_):
            raise RunCancelled("CANCELLED")

        h.guard = denied
        with pytest.raises(RunCancelled):
            await h.tool("financial", args, invoke, scope="org-a")
        assert len(calls) == 2

    asyncio.run(check())


def test_context_failure_generates_report(ledger, monkeypatch):
    from disclosure_ai.workflow import initial as inputs

    def fail(*args):
        raise ValueError("invalid document")

    monkeypatch.setattr(inputs, "search_documents", fail)

    async def check():
        h = Harness("task", ledger, fake_model)
        tools = FakeTools()
        graph = AnalysisGraph(h, tools, InMemorySaver()).graph
        result = await graph.ainvoke(initial(), {"configurable": {"thread_id": "context-failure"}})
        assert result["output"]["report_id"] == "report"
        assert any("PREPARE" in warning for warning in result["warnings"])
        assert ledger.row("task")["turns"] == 0
        assert "IMPACT" not in [
            json.loads(e["payload"]).get("stage") for e in ledger.events("task")
        ]

    asyncio.run(check())


def test_expired_run_preserves_nested_checkpoint_sources_without_network(ledger):
    source = {"document_id": "doc", "location": "line:1", "quote": "계약금액은 80입니다."}
    nested = SimpleNamespace(
        values={
            "documents": [{"document_id": "doc", "text": source["quote"]}],
            "context": [source],
        },
        tasks=[],
    )

    class Graph:
        async def ainvoke(self, state, config):
            await asyncio.Event().wait()

        async def aget_state(self, config, **kwargs):
            return SimpleNamespace(values=initial(), tasks=[SimpleNamespace(state=nested)])

    class Tools:
        async def call(self, *args):
            raise AssertionError("expired run must not call network")

    async def check():
        ledger.db.execute("UPDATE runs SET started=? WHERE id='task'", (time.time() - 121,))
        ledger.db.commit()
        result = await execute(
            Graph(), Harness("task", ledger), Tools(), {}, None, initial()["request"], "org"
        )
        report = result["output"]["report"]
        assert result["output"]["status"] == "SAVE_FAILED"
        assert report["report_json"]["sources"][0]["quote"] == source["quote"]
        assert len(report["report_json"]["sections"]) == 7
        assert ledger.row("task")["turns"] == 0
        assert ledger.row("task")["report"]

    asyncio.run(check())


def test_control_calls_and_retry_save_share_bounded_transport(ledger, monkeypatch):
    from disclosure_ai.services import business

    calls = []

    async def mcp(service, name, args):
        calls.append(name)
        return (
            {"error": "MCP_UNAVAILABLE", "retryable": True}
            if len(calls) < 3
            else {"status": "RUNNING"}
        )

    monkeypatch.setattr(business, "mcp_call", mcp)

    class Tools:
        count = 0

        async def call(self, name, args):
            self.count += 1
            assert args["report"] == {"content": "보존한 보고서"}
            return (
                {"error": "TEMPORARY", "retryable": True}
                if self.count < 3
                else {"status": "COMPLETED"}
            )

    async def check():
        h = Harness("task", ledger)
        with bind(h):
            result = await internal_request("00000000-0000-0000-0000-000000000001", "GET", "status")
        assert result["status"] == "RUNNING" and len(calls) == 3
        tools = Tools()
        ledger.db.execute("UPDATE runs SET started=? WHERE id='task'", (time.time() - 121,))
        ledger.db.commit()
        result = await retry_save(h, tools, {"content": "보존한 보고서"})
        assert result["status"] == "COMPLETED" and tools.count == 3
        assert ledger.row("task")["turns"] == 0
        assert len([e for e in ledger.events("task") if e["kind"] == "CONTROL_CALL"]) == 6

        async def fail(*args):
            raise ConnectionError("network unavailable")

        tools.call = fail
        result = await retry_save(h, tools, {"content": "보존한 보고서"})
        assert result["status"] == "SAVE_FAILED"
        assert result["report"]["content"] == "보존한 보고서"
        assert ledger.row("task")["turns"] == 0

    asyncio.run(check())


def test_report_checks_generated_text_without_rechecking_raw_tables(ledger):
    from test_analysis import filing

    from disclosure_ai.workflow.reporting import report

    async def model(role, context, schema):
        if role == "report":
            assert context["facts"]["corrections"] and not context["facts"]["proposals"]
        if role == "output_check":
            assert all(not row["text"].startswith("원문 항목") for row in context["sentences"])
        return await fake_model(role, context, schema)

    async def check():
        graph = AnalysisGraph(Harness("task", ledger, model), FakeTools(), InMemorySaver())
        state = {
            **initial(),
            "filing": {
                "changes": [
                    {**filing()["changes"][0], "label": "원문 항목 " + str(i)} for i in range(150)
                ]
            },
            "documents": filing()["documents"],
            "context": filing()["changes"],
            "base": await fake_model("base", {}, None),
        }
        result = await report(graph, state)
        assert result["report"]["report_json"]["sections"]["correction"]
        assert result["report"]["report_json"]["sections"]["summary"]
        assert ledger.row("task")["turns"] == 2

    asyncio.run(check())


def test_lookup_budget_and_wait_limit_end_selected_job(ledger):
    from disclosure_ai.workflow import shared

    async def check():
        h = Harness("task", ledger)
        tools = FakeTools()
        ledger.db.execute("UPDATE runs SET tokens=48000 WHERE id='task'")
        ledger.db.commit()
        limited = await h.tool("financial", {}, tools.call)
        assert limited["error"] == "LIMIT_REACHED" and not tools.calls
        saved = await h.tool("business_save_report", {}, tools.call, report=True)
        assert saved["status"] == "COMPLETED"
        args = {"query": "same"}
        key = hashlib.sha256(
            json.dumps(["", "academic", args], sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        h.inflight[key] = asyncio.get_running_loop().create_future()
        h.remaining = lambda report=False: 0.01
        response = await h.tool("academic", args, tools.call)
        assert response["error"] == "WAIT_LIMIT"
        assert not h.inflight[key].cancelled()
        selection = {
            "perspective_type": "FINANCE",
            "selection_reason": "근거 확인",
            "question": "실적",
        }
        state = {
            **initial(),
            "documents": [],
            "context": [],
            "jobs": {"FINANCE": {"status": "NEEDS_TOOLS", "selection": selection}},
            "lookup_results": [{"kind": "FINANCE", "tool": "academic", "response": response}],
        }
        result = await shared.publish(SimpleNamespace(h=h, tools=tools), state)
        assert result["results"]["FINANCE"]["status"] == "LIMIT_REACHED"
        assert shared.resume(result) == "REPORT_AGENT"
        h.inflight[key].set_result({"sources": []})

    asyncio.run(check())
