import asyncio
from functools import partial

from langgraph.graph import END, START, StateGraph

from disclosure_ai.domain.errors import RunCancelled
from disclosure_ai.runtime.harness import Harness
from disclosure_ai.workflow import routing
from disclosure_ai.workflow.nodes.analyze_impact import impact
from disclosure_ai.workflow.nodes.analyze_perspective import perspective
from disclosure_ai.workflow.nodes.collect_inputs import collect
from disclosure_ai.workflow.nodes.execute_tools import lookup
from disclosure_ai.workflow.nodes.generate_report import report
from disclosure_ai.workflow.nodes.join_results import join
from disclosure_ai.workflow.nodes.prepare_evidence import prepare
from disclosure_ai.workflow.nodes.prepare_tools import requests
from disclosure_ai.workflow.nodes.publish_evidence import publish
from disclosure_ai.workflow.nodes.register_perspectives import register
from disclosure_ai.workflow.nodes.save_report import save
from disclosure_ai.workflow.state import State


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
        for name, function in [("COLLECT", collect), ("PREPARE", prepare), ("IMPACT", impact)]:
            initial.add_node(name, partial(self.protected, name, function))
        initial.add_edge(START, "COLLECT")
        initial.add_conditional_edges("COLLECT", lambda s: END if s.get("warnings") else "PREPARE")
        initial.add_conditional_edges(
            "PREPARE", lambda s: END if s.get("stage_failed") else "IMPACT"
        )
        initial.add_edge("IMPACT", END)
        parallel = StateGraph(State)
        parallel.add_node("REGISTER", partial(self.protected, "REGISTER", register))
        parallel.add_node("perspective", partial(perspective, self))
        parallel.add_edge(START, "REGISTER")
        parallel.add_conditional_edges(
            "REGISTER", lambda s: END if s.get("stage_failed") else routing.selected(s)
        )
        parallel.add_edge("perspective", END)
        shared_graph = StateGraph(State)
        shared_graph.add_node("STATUS", lambda s: {})
        for name, function in [
            ("KEY", requests),
            ("SHARED", lookup),
            ("RESULT", publish),
            ("JOIN", join),
        ]:
            shared_graph.add_node(name, partial(self.protected, name, function))
        shared_graph.add_edge(START, "STATUS")
        shared_graph.add_conditional_edges("STATUS", routing.status)
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
        graph.add_node("REPORT_AGENT", partial(report, self))
        graph.add_node("SAVE", partial(save, self))
        graph.add_edge(START, "REQUEST")
        graph.add_edge("REQUEST", "S1")
        graph.add_conditional_edges(
            "S1", lambda s: "S2" if s.get("base", {}).get("selected") else "S3"
        )
        graph.add_edge("S2", "S3")
        graph.add_conditional_edges(
            "S3", lambda s: "REPORT_AGENT" if s.get("stage_failed") else routing.resume(s)
        )
        graph.add_edge("REPORT_AGENT", "SAVE")
        graph.add_edge("SAVE", END)
        return graph.compile(checkpointer=checkpointer)
