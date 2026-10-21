"""도구 구현은 모의 서버로 대체하고 AI MCP 클라이언트의 호출만 검사합니다."""

import asyncio
import socket
import threading
import time

import uvicorn
from mcp.server.fastmcp import Context, FastMCP

from disclosure_ai.business import mcp_call
from disclosure_ai.tools import Tools


def test_mcp_client_contract_and_error_redaction(monkeypatch):
    mcp = FastMCP("test-backend", stateless_http=True, json_response=True)
    key = "test-internal-key-at-least-32-bytes-long"
    calls = []

    @mcp.tool()
    async def get_disclosure(receipt_no: str, ctx: Context) -> dict:
        calls.append(receipt_no)
        assert "X-Internal-API-Key" not in ctx.request_context.request.headers
        return {"documents": [{"document_id": "test", "text": "검증용 자료"}]}

    @mcp.tool()
    async def unavailable(query: str) -> dict:
        raise ValueError(
            '{"code":"OPENDART_UNAVAILABLE","status_code":503,"message":"private-provider-error"}'
        )

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    monkeypatch.setenv("INTERNAL_API_KEY", key)
    monkeypatch.setenv("BUSINESS_MCP_URL", f"http://127.0.0.1:{port}/mcp")
    server = uvicorn.Server(
        uvicorn.Config(mcp.streamable_http_app(), host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.01)
    assert server.started

    async def check():
        tools = Tools("")
        result = await mcp_call("BUSINESS", "get_disclosure", {"receipt_no": "20261020000001"})
        assert result["documents"][0]["text"] == "검증용 자료"
        assert calls == ["20261020000001"]
        missing = await tools.call("market", {})
        assert missing == {"error": "TOOL_NOT_AVAILABLE", "tool": "market"}
        failed = await mcp_call("BUSINESS", "unavailable", {"query": "risk"})
        assert failed == {"error": "OPENDART_UNAVAILABLE", "retryable": True, "tool": "unavailable"}
        assert (await tools.call("academic", {"query": "risk"}))["error"] == "TOOL_NOT_AVAILABLE"
        assert "private-provider-error" not in str(failed)

    try:
        asyncio.run(check())
    finally:
        server.should_exit = True
        thread.join(timeout=5)
