import json

import anyio
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.errors import RagError


class McpSources:
    """Official SDK transport; clients are reused and sessions close after each call."""
    def __init__(self, client: httpx.AsyncClient, business_url: str, external_url: str, timeout: float):
        self.client, self.business_url, self.external_url = client, business_url, external_url
        self.timeout = timeout

    async def _call(self, url, name, arguments):
        try:
            with anyio.fail_after(self.timeout):
                async with streamable_http_client(url, http_client=self.client) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.call_tool(name, arguments)
                        if result.isError:
                            raise RagError("MCP_TOOL_FAILED", f"Upstream tool {name} failed")
                        value = result.structuredContent
                        if value is None:
                            value = json.loads(next(c.text for c in result.content if c.type == "text"))
                        if not isinstance(value, dict):
                            raise ValueError("Expected object")
                        return value
        except RagError:
            raise
        except Exception:
            # ExceptionGroup/transport errors may contain URLs and remote bodies.
            raise RagError("MCP_UNAVAILABLE", f"Upstream tool {name} unavailable or malformed") from None

    async def get_context(self, task_id):
        return await self._call(self.business_url, "get_analysis_context", {"task_id": str(task_id)})

    async def get_disclosure(self, receipt_no):
        return await self._call(self.external_url, "get_disclosure", {"receipt_no": receipt_no})

    async def news_search(self, query, start=1, display=100):
        return await self._call(self.external_url, "naver_news_search", {
            "query": query, "start": start, "display": display})
