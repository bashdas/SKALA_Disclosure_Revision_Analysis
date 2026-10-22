import os

import httpx

from disclosure_ai.infrastructure.mcp.client import (
    BusinessError,
    RunCancelled,
    internal_request,
    mcp_call,
)


class BusinessMcpAdapter:
    def __init__(self, authorization: str):
        self.authorization = authorization

    async def authorize(self, request: dict) -> dict:
        base = os.environ.get("BUSINESS_API_BASE_URL", "http://127.0.0.1:8080")
        async with httpx.AsyncClient(base_url=base, timeout=10) as client:
            response = await client.get(
                f"/api/v1/memos/{request['memo_id']}/versions/{request['base_memo_version']}",
                headers={"Authorization": self.authorization},
            )
            response.raise_for_status()
            memo = response.json()
            if (
                memo["memo_id"] != request["memo_id"]
                or memo["version"] != request["base_memo_version"]
            ):
                raise ValueError("메모 ID 또는 고정 버전이 일치하지 않습니다.")
        context = await internal_request(request["analysis_task_id"], "GET", "context")
        if (
            context["memo"]["id"] != request["memo_id"]
            or context["memo"]["version"] != request["base_memo_version"]
            or context["disclosure_receipt_no"] != request["disclosure_receipt_no"]
        ):
            raise BusinessError("TASK_INPUT_MISMATCH")
        return {
            "scope": f"{context['organization_id']}:{request['memo_id']}:{request['base_memo_version']}"
        }

    async def ensure_active(self, task_id: str):
        status = await internal_request(task_id, "GET", "status")
        if status["status"] == "CANCELLED":
            raise RunCancelled("ANALYSIS_CANCELLED")
        if status["status"] in {"COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED"}:
            raise BusinessError("ANALYSIS_NOT_ACTIVE")
        return status

    async def stage(self, task_id: str, stage: str):
        status = await self.ensure_active(task_id)
        if status["status"] == "QUEUED":
            status = await internal_request(task_id, "POST", "state", {"status": "RUNNING"})
        stages = [
            "REQUEST_VALIDATION",
            "INPUT_COLLECTION",
            "RAG_PREPARATION",
            "BASE_ANALYSIS",
            "PERSPECTIVE_ANALYSIS",
            "REPORT_GENERATION",
            "REPORT_SAVE",
        ]
        current = status.get("current_stage")
        # 체크포인트 재개가 이미 반영된 단계를 되돌리지 않도록 합니다.
        if current in stages and stages.index(current) >= stages.index(stage):
            return
        await internal_request(task_id, "POST", "state", {"stage": stage})
        if stage in {"INPUT_COLLECTION", "RAG_PREPARATION", "BASE_ANALYSIS", "REPORT_GENERATION"}:
            await internal_request(
                task_id,
                "POST",
                "events",
                {
                    "event_type": stage + "_STARTED",
                    "payload": {"stage": stage},
                },
            )

    async def perspective(self, task_id: str, selection: dict, result=None):
        await self.ensure_active(task_id)
        item = await internal_request(
            task_id,
            "POST",
            "perspectives",
            {
                **selection,
                "max_tool_calls": 3,
                "timeout_seconds": 90,
            },
        )
        if item["status"] not in {"REGISTERED", "RUNNING"}:
            return
        path = "perspectives/" + item["perspective_id"]
        if item["status"] == "REGISTERED":
            await internal_request(task_id, "PATCH", path, {"status": "RUNNING"})
        if result is not None:
            await internal_request(
                task_id, "PATCH", path, {"status": result["status"], "result": result}
            )

    async def call(self, name: str, args: dict) -> dict:
        if name == "business_get_memo":
            context = await mcp_call(
                "BUSINESS", "get_analysis_context", {"task_id": args["task_id"]}
            )
            if context.get("error"):
                return context
            memo = context["memo"]
            if memo["id"] != args["memo_id"] or memo["version"] != args["version"]:
                return {"error": "TASK_INPUT_MISMATCH"}
            return {
                "document_id": f"memo:{memo['id']}:v{memo['version']}",
                "text": memo["content"],
                "version": memo["version"],
            }

        if name == "business_save_report":
            status = await mcp_call("BUSINESS", "get_analysis_status", {"task_id": args["task_id"]})
            if status.get("error"):
                return status
            if status["status"] in {"QUEUED", "RUNNING"}:
                try:
                    if status.get("current_stage") in {None, "REQUEST_VALIDATION"}:
                        await self.stage(args["task_id"], "INPUT_COLLECTION")
                    await self.stage(args["task_id"], "REPORT_GENERATION")
                except RunCancelled:
                    raise
                except BusinessError as error:
                    return {"error": error.code, "retryable": error.retryable}
            report = args["report"]
            return await mcp_call(
                "BUSINESS",
                "save_analysis_report",
                {
                    "task_id": args["task_id"],
                    "content": report["content"],
                    "report": report["report_json"],
                    "has_warnings": report["has_warnings"],
                    "no_additional_analysis_reason": report["no_additional_analysis_reason"],
                },
            )

        return {"error": "TOOL_NOT_AVAILABLE", "tool": name}
