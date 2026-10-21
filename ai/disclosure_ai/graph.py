from functools import partial
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from disclosure_ai import perspectives, reporting
from disclosure_ai.harness import Harness
from disclosure_ai.initial import collect, impact, prepare


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
    rag_ready: bool


class AnalysisGraph:
    def __init__(self, harness: Harness, tools, checkpointer):
        self.h = harness
        self.tools = tools
        self.h.guard = getattr(tools, "ensure_active", None)
        self.graph = self.build(checkpointer)

    async def stage(self, state, name, payload=None):
        if hasattr(self.tools, "stage"):
            await self.tools.stage(self.h.task_id, name)
        self.h.ledger.event(self.h.task_id, "STAGE", stage=name, payload=payload or {})

    async def request(self, state):
        await self.stage(state, "REQUEST_VALIDATION")
        return {}

    def build(self, checkpointer):
        initial = StateGraph(State)
        for name, function in [
            ("COLLECT", partial(collect, self)),
            ("PREPARE", partial(prepare, self)),
            ("IMPACT", partial(impact, self)),
        ]:
            initial.add_node(name, function)
        initial.add_edge(START, "COLLECT")
        initial.add_conditional_edges("COLLECT", lambda s: END if s.get("warnings") else "PREPARE")
        initial.add_edge("PREPARE", "IMPACT")
        initial.add_edge("IMPACT", END)
        parallel = StateGraph(State)
        parallel.add_node("REGISTER", partial(perspectives.register, self))
        parallel.add_node("perspective", partial(perspectives.perspective, self))
        parallel.add_edge(START, "REGISTER")
        parallel.add_conditional_edges("REGISTER", perspectives.selected)
        parallel.add_edge("perspective", END)
        final = StateGraph(State)
        for name, function in [
            ("JOIN", partial(reporting.join, self)),
            ("REPORT_AGENT", partial(reporting.report, self)),
            ("SAVE", partial(reporting.save, self)),
        ]:
            final.add_node(name, function)
        final.add_edge(START, "JOIN")
        final.add_edge("JOIN", "REPORT_AGENT")
        final.add_edge("REPORT_AGENT", "SAVE")
        final.add_edge("SAVE", END)
        graph = StateGraph(State)
        graph.add_node("REQUEST", self.request)
        graph.add_node("S1", initial.compile())
        graph.add_node("S2", parallel.compile())
        graph.add_node("S3", final.compile())
        graph.add_edge(START, "REQUEST")
        graph.add_edge("REQUEST", "S1")
        graph.add_conditional_edges(
            "S1", lambda s: "S2" if s.get("base", {}).get("selected") else "S3"
        )
        graph.add_edge("S2", "S3")
        graph.add_edge("S3", END)
        return graph.compile(checkpointer=checkpointer)
