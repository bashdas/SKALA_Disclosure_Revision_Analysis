"""백엔드가 발행한 작업 ID로 분석과 보고서 저장을 수행합니다."""

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Literal
from uuid import UUID

import pika
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import Field

from disclosure_ai.harness.ledger import Ledger
from disclosure_ai.harness.runtime import Harness
from disclosure_ai.schemas import AnalysisRequest, Model
from disclosure_ai.services.business import (
    BusinessError,
    RunCancelled,
    fixed_request,
    internal_request,
)
from disclosure_ai.services.tools import Tools
from disclosure_ai.workflow.execution import execute, retry_save
from disclosure_ai.workflow.graph import AnalysisGraph


class Message(Model):
    message_id: UUID
    task_id: UUID
    type: Literal["RUN_ANALYSIS"]
    retry_count: int = Field(ge=0)


async def process_task(task_id: str, state: Path, call_model=None) -> dict:
    started = time.time()
    task_id = str(UUID(task_id))
    context = await internal_request(task_id, "GET", "context")
    if context["status"] in {"COMPLETED", "COMPLETED_WITH_WARNINGS", "CANCELLED", "FAILED"}:
        return {"status": context["status"]}
    request = AnalysisRequest.model_validate(fixed_request(context)).model_dump(mode="json")
    scope = f"{context['organization_id']}:{request['memo_id']}:{request['base_memo_version']}"
    state.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with state.with_suffix(state.suffix + ".lock").open("a") as lock:
        os.chmod(lock.name, 0o600)
        # ponytail: 하나의 공유 상태 파일과 worker 한 개를 사용하며 다중 호스트에는 분산 실행 임대가 필요합니다.
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        ledger = Ledger(str(state))
        harness = None
        tools = Tools("")
        try:
            fingerprint = hashlib.sha256(
                json.dumps(
                    {"request": request, "scope": scope, "memo": context["memo"]},
                    sort_keys=True,
                    ensure_ascii=False,
                ).encode()
            ).hexdigest()
            ledger.begin(
                task_id,
                fingerprint,
                scope + ":" + request["disclosure_receipt_no"],
                started=started,
            )
            row = ledger.row(task_id)
            if row["report"]:
                harness = Harness(task_id, ledger, call_model)
                result = await retry_save(harness, tools, json.loads(row["report"]))
                if result.get("error"):
                    raise BusinessError(result["error"], result.get("retryable", False))
                return result
            if context["status"] in {"SAVING", "SAVE_FAILED"}:
                raise BusinessError("LOCAL_REPORT_MISSING")
            harness = Harness(task_id, ledger, call_model)
            async with AsyncSqliteSaver.from_conn_string(str(state) + ".checkpoints") as saver:
                graph = AnalysisGraph(harness, tools, saver).graph
                config = {
                    "configurable": {"thread_id": task_id + ":" + fingerprint},
                    "recursion_limit": 40,
                }
                checkpoint = await graph.aget_state(config)
                initial = (
                    None
                    if checkpoint.next
                    else {"request": request, "scope": scope, "warnings": [], "results": {}}
                )
                result = await execute(graph, harness, tools, config, initial, request, scope)
                output = result["output"]
                if output.get("status") == "SAVE_FAILED":
                    raise BusinessError(output["error"], True)
                return output
        except RunCancelled:
            ledger.keep(task_id, "result", {"status": "CANCELLED"})
            return {"status": "CANCELLED"}
        finally:
            if harness:
                await harness.close()
            ledger.db.close()


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


def consume(state: Path):
    exchange = os.environ.get("RABBITMQ_EXCHANGE", "analysis.exchange")
    queue = os.environ.get("RABBITMQ_ANALYSIS_QUEUE", "analysis.tasks")
    max_retries = int(os.environ.get("RABBITMQ_MAX_RETRIES", "3"))
    if not 1 <= max_retries <= 10:
        raise ValueError("INVALID_RETRY_LIMIT")
    parameters = pika.URLParameters(os.environ["RABBITMQ_URL"])
    parameters.heartbeat = 30
    parameters.blocked_connection_timeout = 10
    parameters.socket_timeout = 10
    with ThreadPoolExecutor(max_workers=1) as executor:
        while True:
            connection = None
            try:
                connection = pika.BlockingConnection(parameters)
                channel = connection.channel()
                # 큐와 재시도 TTL은 백엔드 Producer가 선언한 구성을 그대로 사용합니다.
                channel.queue_declare(queue=queue, passive=True)
                channel.confirm_delivery()
                channel.basic_qos(prefetch_count=1)

                def settle(
                    delivery_tag, raw, message, future, channel=channel, connection=connection
                ):
                    if not channel.is_open:
                        return
                    try:
                        result = future.result()
                        print(
                            json.dumps(
                                {"task_id": str(message.task_id), "status": result["status"]}
                            ),
                            flush=True,
                        )
                    except Exception as error:
                        attempt = message.retry_count + 1
                        retryable = not isinstance(error, BusinessError) or error.retryable
                        target = (
                            f"analysis.retry.{attempt}"
                            if retryable and attempt <= max_retries
                            else "analysis.dead"
                        )
                        payload = (
                            message.model_copy(update={"retry_count": attempt})
                            .model_dump_json()
                            .encode()
                        )
                        try:
                            channel.basic_publish(
                                exchange=exchange,
                                routing_key=target,
                                body=payload,
                                mandatory=True,
                                properties=pika.BasicProperties(
                                    content_type="application/json",
                                    delivery_mode=2,
                                    message_id=str(message.message_id),
                                    type=message.type,
                                    headers={"retry_count": attempt},
                                ),
                            )
                        except Exception:
                            # 재발행 확인을 받지 못하면 원본 ack를 보내지 않아 유실을 막습니다.
                            connection.close()
                            return
                        print(
                            json.dumps(
                                {
                                    "task_id": str(message.task_id),
                                    "status": target,
                                    "error": type(error).__name__,
                                }
                            ),
                            flush=True,
                        )
                    channel.basic_ack(delivery_tag=delivery_tag)

                def receive(
                    _channel, method, properties, raw, connection=connection, settle=settle
                ):
                    try:
                        if len(raw) > 16384:
                            raise ValueError("MESSAGE_TOO_LARGE")
                        message = Message.model_validate_json(raw)
                    except ValueError:
                        # 잘못된 메시지는 분석하거나 무한 재시도하지 않고 기존 DLQ로 보냅니다.
                        _channel.basic_reject(delivery_tag=method.delivery_tag, requeue=False)
                        return
                    future = executor.submit(
                        asyncio.run, process_message(message, state, max_retries)
                    )

                    def done(completed):
                        try:
                            connection.add_callback_threadsafe(
                                partial(settle, method.delivery_tag, raw, message, completed)
                            )
                        except pika.exceptions.ConnectionWrongStateError:
                            pass

                    future.add_done_callback(done)

                channel.basic_consume(queue=queue, on_message_callback=receive, auto_ack=False)
                channel.start_consuming()
            except KeyboardInterrupt:
                return
            except Exception as error:
                print(
                    json.dumps({"status": "BROKER_RECONNECT", "error": type(error).__name__}),
                    flush=True,
                )
                time.sleep(2)
            finally:
                if connection is not None and connection.is_open:
                    connection.close()


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
