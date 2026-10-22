import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from disclosure_ai.application.services.execute_analysis import process_task
from disclosure_ai.infrastructure.mcp.tool_gateway import Tools
from disclosure_ai.ports.execution import ExecutionDependencies


def test_terminal_task_uses_injected_business_port_without_opening_storage(tmp_path):
    async def internal(task_id, method, route):
        assert method == "GET" and route == "context"
        return {"status": "COMPLETED"}

    def unexpected(*args, **kwargs):
        raise AssertionError("Terminal task must not create a model, repository or graph")

    dependencies = ExecutionDependencies(
        repository=unexpected,
        harness=unexpected,
        tools=unexpected,
        checkpointer=unexpected,
        workflow=unexpected,
        internal_request=internal,
        fixed_request=unexpected,
    )
    assert asyncio.run(
        process_task(str(uuid4()), tmp_path / "state.sqlite", dependencies=dependencies)
    ) == {"status": "COMPLETED"}
    assert not Path(tmp_path / "state.sqlite").exists()


def test_mcp_gateways_can_be_replaced_independently():
    external = SimpleNamespace(call=AsyncMock(return_value={"documents": ["external"]}))
    rag = SimpleNamespace(call=AsyncMock(return_value={"sources": ["rag"]}))
    tools = Tools("", external=external, rag=rag)

    async def check():
        assert await tools.call("disclosure_get_document", {"receipt_no": "test"}) == {
            "documents": ["external"],
        }
        assert await tools.call("search_evidence", {"task_id": "test"}) == {"sources": ["rag"]}
        external.call.assert_awaited_once()
        rag.call.assert_awaited_once()

    asyncio.run(check())
