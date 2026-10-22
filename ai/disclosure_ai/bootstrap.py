"""Composition root: only here are default runtime and external implementations assembled."""

from disclosure_ai.infrastructure.checkpoint.sqlite_checkpointer import open_checkpointer
from disclosure_ai.infrastructure.mcp.client import fixed_request, internal_request
from disclosure_ai.infrastructure.mcp.tool_gateway import Tools
from disclosure_ai.infrastructure.persistence.sqlite_run_repository import Ledger
from disclosure_ai.ports.execution import ExecutionDependencies
from disclosure_ai.runtime.harness import Harness
from disclosure_ai.workflow.graph import AnalysisGraph


def build_dependencies():
    return ExecutionDependencies(
        repository=Ledger,
        harness=Harness,
        tools=Tools,
        checkpointer=open_checkpointer,
        workflow=lambda harness, tools, saver: AnalysisGraph(harness, tools, saver).graph,
        internal_request=internal_request,
        fixed_request=fixed_request,
    )


def build_model_gateway(client=None):
    from openai import AsyncOpenAI

    from disclosure_ai.infrastructure.openai.openai_model_adapter import OpenAIModelAdapter

    return OpenAIModelAdapter(client if client is not None else AsyncOpenAI(max_retries=0))
