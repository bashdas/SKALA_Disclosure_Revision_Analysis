"""최신 Business API의 작업별 내부 계약을 호출합니다."""

import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from uuid import UUID

import httpx
from langsmith import traceable
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from disclosure_ai.harness.transport import invoke


class BusinessError(RuntimeError):
    def __init__(self, code: str, retryable: bool = False):
        self.code, self.retryable = code, retryable
        super().__init__(code)


class RunCancelled(BusinessError):
    pass


@asynccontextmanager
async def connect(url: str, headers: dict | None = None):
    async with httpx.AsyncClient(
        headers=headers or {},
        timeout=httpx.Timeout(8, read=10),
        follow_redirects=False,
        trust_env=False,
    ) as http:
        async with streamable_http_client(url, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


@traceable(run_type="tool", name="mcp-call")
async def mcp_call(service: str, name: str, args: dict) -> dict:
    ports = {"BUSINESS": 8081, "EXTERNAL": 8083, "RAG": 8082}
    url = os.environ.get(service + "_MCP_URL", f"http://127.0.0.1:{ports[service]}/mcp")
    try:
        async with asyncio.timeout(10):
            # 현재 백엔드 MCP는 내부 네트워크 방식이며 외부 서비스 키를 Agent가 전달하지 않습니다.
            async with connect(url) as session:
                listed = await session.list_tools()
                if not any(tool.name == name for tool in listed.tools):
                    return {"error": "TOOL_NOT_AVAILABLE", "tool": name}
                result = await session.call_tool(name, args)
        if result.isError:
            for part in result.content:
                if part.type != "text" or len(part.text) > 16384:
                    continue
                start = part.text.find("{")
                if start < 0:
                    continue
                try:
                    error, _ = json.JSONDecoder().raw_decode(part.text[start:])
                except ValueError:
                    continue
                if not isinstance(error, dict):
                    continue
                code = error.get("code", "")
                if isinstance(code, str) and re.fullmatch(r"[A-Z0-9_]{1,100}", code):
                    retryable = error.get("status_code") in {429, 500, 502, 503, 504} or code in {
                        "BUSINESS_API_TIMEOUT",
                        "BUSINESS_API_CONNECTION_FAILED",
                        "OPENDART_TIMEOUT",
                        "OPENDART_UNAVAILABLE",
                        "OPENDART_RATE_LIMITED",
                        "SCHOLAR_TIMEOUT",
                        "SCHOLAR_UNAVAILABLE",
                        "SCHOLAR_RATE_LIMITED",
                        "MCP_UNAVAILABLE",
                        "RAG_DATABASE_FAILED",
                    }
                    return {"error": code, "retryable": retryable, "tool": name}
            return {"error": "MCP_TOOL_ERROR", "tool": name}
        value = result.structuredContent
        if value is None:
            value = json.loads(next(part.text for part in result.content if part.type == "text"))
        return value if isinstance(value, dict) else {"error": "INVALID_TOOL_OUTPUT"}
    except (ValueError, StopIteration):
        return {"error": "INVALID_TOOL_OUTPUT"}
    except Exception:
        # SDK의 ExceptionGroup에도 주소나 응답 원문이 들어갈 수 있습니다.
        return {"error": "MCP_UNAVAILABLE", "retryable": True, "tool": name}


async def internal_request(task_id: str, method: str, suffix: str, body=None) -> dict:
    task_id = str(UUID(task_id))
    routes = {
        ("GET", "context"): "get_analysis_context",
        ("GET", "status"): "get_analysis_status",
        ("POST", "state"): "update_analysis_state",
        ("POST", "events"): "report_analysis_event",
        ("POST", "perspectives"): "register_perspective",
        ("POST", "report"): "save_analysis_report",
    }
    args = {"task_id": task_id, **(body or {})}
    if method == "PATCH" and suffix.startswith("perspectives/"):
        args["perspective_id"] = str(UUID(suffix.split("/", 1)[1]))
        name = "update_perspective"
    else:
        name = routes.get((method, suffix))
    if name is None:
        raise BusinessError("INVALID_INTERNAL_PATH")
    result = await invoke(name, lambda: mcp_call("BUSINESS", name, args))
    if result.get("error"):
        raise BusinessError(result["error"], result.get("retryable", False))
    return result


def fixed_request(context: dict) -> dict:
    """기업이 미확정이면 표시용 상태를 남기고 메모에서 기업을 추측하지 않습니다."""
    return {
        "analysis_task_id": context["task_id"],
        "memo_id": context["memo"]["id"],
        "base_memo_version": context["memo"]["version"],
        "disclosure_receipt_no": context["disclosure_receipt_no"],
        "company_name_snapshot": context.get("company_name") or "기업명 미확정",
        "corp_code": context.get("corp_code"),
        "thread_id": context["task_id"],
        "disclosure_type": (
            "CORRECTION" if context.get("filing_type") == "정정공시"
            and context.get("is_correction") is True else
            "NEW" if context.get("filing_type") == "신규공시"
            and context.get("is_correction") is False else "UNKNOWN"
        ),
    }
