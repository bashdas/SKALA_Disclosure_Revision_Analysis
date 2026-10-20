from typing import Any
from uuid import UUID

from mcp.server.fastmcp import FastMCP

from app.client import BusinessAPIClient


def register_tools(mcp: FastMCP, client: BusinessAPIClient) -> None:
    @mcp.tool()
    async def get_analysis_context(task_id: UUID) -> dict[str, Any]:
        """Get server-fixed analysis context and its base MemoVersion content."""
        return await client.request("GET", f"/internal/analyses/{task_id}/context")

    @mcp.tool()
    async def get_analysis_status(task_id: UUID) -> dict[str, Any]:
        """Get current status; stop analysis work if cancelled is true."""
        return await client.request("GET", f"/internal/analyses/{task_id}/status")

    @mcp.tool()
    async def report_analysis_event(task_id: UUID, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Append an Agent semantic event; server assigns sequence. Retrying can duplicate it."""
        return await client.request("POST", f"/internal/analyses/{task_id}/events", {"event_type": event_type, "payload": payload})

    @mcp.tool()
    async def update_analysis_state(task_id: UUID, status: str | None = None, stage: str | None = None,
        has_warnings: bool | None = None, error_stage: str | None = None,
        error_code: str | None = None, error_message: str | None = None) -> dict[str, Any]:
        """Request status/stage updates; Business API validates all transitions."""
        body = {"status": status, "stage": stage, "has_warnings": has_warnings,
                "error_stage": error_stage, "error_code": error_code, "error_message": error_message}
        return await client.request("POST", f"/internal/analyses/{task_id}/state", {key: value for key, value in body.items() if value is not None})

    @mcp.tool()
    async def register_perspective(task_id: UUID, perspective_type: str, selection_reason: str,
        question: str, max_tool_calls: int, timeout_seconds: int) -> dict[str, Any]:
        """Register a perspective already selected by Agent; duplicate policy belongs to API."""
        return await client.request("POST", f"/internal/analyses/{task_id}/perspectives", {
            "perspective_type": perspective_type, "selection_reason": selection_reason, "question": question,
            "max_tool_calls": max_tool_calls, "timeout_seconds": timeout_seconds})

    @mcp.tool()
    async def update_perspective(task_id: UUID, perspective_id: UUID, status: str,
        result: dict[str, Any] | None = None, failure_code: str | None = None,
        failure_message: str | None = None) -> dict[str, Any]:
        """Update a task-bound perspective through the Business API state machine."""
        body = {"status": status, "result": result, "failure_code": failure_code, "failure_message": failure_message}
        return await client.request("PATCH", f"/internal/analyses/{task_id}/perspectives/{perspective_id}",
            {key: value for key, value in body.items() if value is not None})

    @mcp.tool()
    async def save_analysis_report(task_id: UUID, content: str, report: dict[str, Any], has_warnings: bool = False,
        no_additional_analysis_reason: str | None = None) -> dict[str, Any]:
        """Persist an Agent-generated report. Business API owns transactions/idempotency."""
        body = {"content": content, "report": report, "has_warnings": has_warnings}
        if no_additional_analysis_reason is not None:
            body["no_additional_analysis_reason"] = no_additional_analysis_reason
        return await client.request("POST", f"/internal/analyses/{task_id}/report", body)
