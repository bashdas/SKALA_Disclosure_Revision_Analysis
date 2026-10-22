import asyncio
from functools import partial
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from disclosure_ai.harness.runtime import Harness
from disclosure_ai.services.business import RunCancelled
from disclosure_ai.workflow import perspectives, reporting, shared
from disclosure_ai.workflow.initial import collect, impact, prepare


class State(TypedDict, total=False):
    request: dict
    scope: str
    filing: dict
    memo: dict
    documents: list
    context: list
    base: dict
    results: Annotated[dict, lambda a, b: {**a, **b}]
    warnings: Annotated[list, lambda a, b: list(dict.fromkeys(a + b))]
    report: dict
    output: dict
    selection: dict
    stage_failed: bool
    rag_ready: bool
    jobs: Annotated[dict, lambda a, b: {**a, **b}]
    lookups: list
    lookup_results: list


class AnalysisGraph:
    def __init__(self, harness: Harness, tools, checkpointer):
        self.h = harness
        self.tools = tools
        self.h.guard = getattr(tools, "ensure_active", None)
        self.graph = self.build(checkpointer)

    async def stage(self, state, name, payload=None):
        if hasattr(self.tools, "stage"):
            try:
                await self.tools.stage(self.h.task_id, name)
            except RunCancelled:
                raise
            except Exception as error:
                self.h.ledger.event(
                    self.h.task_id, "STAGE_NOTIFY_FAILED", stage=name, error=type(error).__name__
                )
        self.h.ledger.event(self.h.task_id, "STAGE", stage=name, payload=payload or {})

    async def request(self, state):
        await self.stage(state, "REQUEST_VALIDATION")
        return {}

    async def protected(self, name, function, state):
        try:
            if name not in {"REPORT_AGENT", "SAVE"}:
                async with asyncio.timeout(max(0.001, self.h.remaining())):
                    return await function(self, state)
            return await function(self, state)
        except RunCancelled:
            raise
        except Exception as error:
            self.h.ledger.event(
                self.h.task_id, "STAGE_FAILED", stage=name, error=type(error).__name__
            )
            return {
                "warnings": [name + " 처리 실패: " + type(error).__name__],
                "stage_failed": True,
            }

    def build(self, checkpointer):
        initial = StateGraph(State)
        for name, function in [("COLLECT", collect), ("PREPARE", prepare),
                               ("IMPACT_NEW", impact), ("IMPACT_CORRECTION", impact),
                               ("IMPACT_UNKNOWN", impact)]:
            initial.add_node(name, partial(self.protected, name, function))
        initial.add_edge(START, "COLLECT")
        initial.add_conditional_edges("COLLECT", lambda s: END if s.get("warnings") else "PREPARE")
        initial.add_conditional_edges(
            "PREPARE", lambda s: END if s.get("stage_failed") else
            "IMPACT_" + s["filing"].get("analysis_type", "UNKNOWN")
        )
        for name in ("IMPACT_NEW", "IMPACT_CORRECTION", "IMPACT_UNKNOWN"):
            initial.add_edge(name, END)
        parallel = StateGraph(State)
        parallel.add_node("REGISTER", partial(self.protected, "REGISTER", perspectives.register))
        parallel.add_node("perspective", partial(perspectives.perspective, self))
        parallel.add_edge(START, "REGISTER")
        parallel.add_conditional_edges(
            "REGISTER", lambda s: END if s.get("stage_failed") else perspectives.selected(s)
        )
        parallel.add_edge("perspective", END)
        shared_graph = StateGraph(State)
        shared_graph.add_node("STATUS", lambda s: {})
        for name, function in [
            ("KEY", shared.requests),
            ("SHARED", shared.lookup),
            ("RESULT", shared.publish),
            ("JOIN", reporting.join),
        ]:
            shared_graph.add_node(name, partial(self.protected, name, function))
        shared_graph.add_edge(START, "STATUS")
        shared_graph.add_conditional_edges("STATUS", shared.status)
        shared_graph.add_conditional_edges(
            "KEY", lambda s: "JOIN" if s.get("stage_failed") else "SHARED"
        )
        shared_graph.add_conditional_edges(
            "SHARED", lambda s: "JOIN" if s.get("stage_failed") else "RESULT"
        )
        shared_graph.add_edge("RESULT", "JOIN")
        shared_graph.add_edge("JOIN", END)
        graph = StateGraph(State)
        graph.add_node("REQUEST", self.request)
        graph.add_node("S1", initial.compile())
        graph.add_node("S2", parallel.compile())
        graph.add_node("S3", shared_graph.compile())
        graph.add_node("REPORT_AGENT", partial(reporting.report, self))
        graph.add_node("SAVE", partial(reporting.save, self))
        graph.add_edge(START, "REQUEST")
        graph.add_edge("REQUEST", "S1")
        graph.add_conditional_edges(
            "S1", lambda s: "S2" if s.get("base", {}).get("selected") else "S3"
        )
        graph.add_edge("S2", "S3")
        graph.add_conditional_edges(
            "S3", lambda s: "REPORT_AGENT" if s.get("stage_failed") else shared.resume(s)
        )
        graph.add_edge("REPORT_AGENT", "SAVE")
        graph.add_edge("SAVE", END)
        return graph.compile(checkpointer=checkpointer)
