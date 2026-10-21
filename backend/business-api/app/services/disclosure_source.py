"""공시 조회는 External MCP의 OpenDART 도구를 호출합니다."""
import json
import anyio
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from app.core.config import Settings
from app.domain.disclosure_exceptions import DisclosureError


class DisclosureSource:
    def __init__(self, settings: Settings):
        self.settings = settings

    def call(self, tool: str, arguments: dict) -> dict:
        return anyio.run(self._call, tool, arguments)

    async def _call(self, tool: str, arguments: dict) -> dict:
        try:
            with anyio.fail_after(self.settings.external_mcp_timeout_seconds):
                async with httpx.AsyncClient(timeout=self.settings.external_mcp_timeout_seconds, trust_env=False) as client:
                    async with streamable_http_client(self.settings.external_mcp_url, http_client=client) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            result = await session.call_tool(tool, arguments)
                            if result.isError:
                                raise DisclosureError()
                            value = result.structuredContent
                            if value is None:
                                value = json.loads(next(item.text for item in result.content if item.type == "text"))
                            if not isinstance(value, dict):
                                raise ValueError()
                            return value
        except DisclosureError:
            raise
        except Exception:
            # 통신 오류에 포함될 수 있는 내부 주소와 원문 응답은 사용자 오류에 노출하지 않습니다.
            raise DisclosureError() from None
