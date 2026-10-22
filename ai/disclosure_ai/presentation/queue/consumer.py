import argparse
import asyncio
import json
import sqlite3
from pathlib import Path
from uuid import UUID

import pika as pika

from disclosure_ai.application.services.execute_analysis import process_task as execute_task
from disclosure_ai.bootstrap import build_dependencies
from disclosure_ai.infrastructure.mcp.client import (
    BusinessError,
    internal_request,
)
from disclosure_ai.infrastructure.mcp.tool_gateway import Tools
from disclosure_ai.infrastructure.messaging.rabbitmq_consumer import consume as consume_messages
from disclosure_ai.presentation.queue.messages import Message


async def process_task(task_id, state, call_model=None):
    return await execute_task(task_id, state, call_model, dependencies=build_dependencies())


async def process_message(message: Message, state: Path, max_retries: int) -> dict:
    try:
        return await process_task(str(message.task_id), state)
    except Exception as error:
        retryable = not isinstance(error, BusinessError) or error.retryable
        if retryable and message.retry_count < max_retries:
            raise
        task_id = str(message.task_id)
        status = await internal_request(task_id, "GET", "status")
        # 저장 전 통신이 실패했어도 확보한 보고서의 재저장 경로를 보존합니다.
        if status["status"] == "RUNNING":

            def has_report():
                if not state.exists():
                    return False
                with sqlite3.connect(state.resolve().as_uri() + "?mode=ro", uri=True) as db:
                    row = db.execute("SELECT report FROM runs WHERE id=?", (task_id,)).fetchone()
                return bool(row and row[0])

            if await asyncio.to_thread(has_report):
                if status.get("current_stage") != "REPORT_GENERATION":
                    tools = Tools("")
                    if status.get("current_stage") in {None, "REQUEST_VALIDATION"}:
                        await tools.stage(task_id, "INPUT_COLLECTION")
                    await tools.stage(task_id, "REPORT_GENERATION")
                await internal_request(task_id, "POST", "state", {"status": "SAVING"})
                status = {"status": "SAVING"}
        # 저장 중 실패는 재저장 가능한 상태로 남기고 종료된 작업은 보존합니다.
        target = {"QUEUED": "FAILED", "RUNNING": "FAILED", "SAVING": "SAVE_FAILED"}.get(
            status["status"]
        )
        if target:
            await internal_request(
                task_id,
                "POST",
                "state",
                {
                    "status": target,
                    "error_code": "AI_RETRIES_EXHAUSTED" if retryable else "AI_EXECUTION_FAILED",
                    "error_message": "AI 실행을 완료하지 못했습니다. 보존된 상태와 실패 큐를 확인해야 합니다.",
                },
            )
        raise


def consume(state):
    return consume_messages(state, process_message, Message)


def main():
    parser = argparse.ArgumentParser(description="기존 백엔드의 분석 작업을 처리합니다.")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument(
        "--task-id", type=UUID, help="지정하면 큐 연결 없이 해당 작업 한 개를 처리합니다."
    )
    args = parser.parse_args()
    if args.task_id:
        try:
            result = asyncio.run(process_task(str(args.task_id), args.state))
            print(json.dumps(result, ensure_ascii=False))
        except Exception as error:
            print(json.dumps({"status": "FAILED", "error": type(error).__name__}))
            raise SystemExit(1) from None
    else:
        consume(args.state)


if __name__ == "__main__":
    main()
