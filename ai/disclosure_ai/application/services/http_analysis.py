import hashlib
import json

from disclosure_ai.application.services.analysis_service import execute
from disclosure_ai.domain.errors import RunCancelled


async def run_http_analysis(
    body,
    tools,
    scope,
    *,
    ledger,
    checkpointer,
    active,
    harness_factory,
    graph_factory,
    internal_request,
):
    task_id = str(body.analysis_task_id)
    harness = harness_factory(task_id, ledger)
    try:
        graph = graph_factory(harness, tools, checkpointer).graph
        config = {
            "configurable": {
                "thread_id": hashlib.sha256(
                    (str(body.analysis_task_id) + scope["scope"] + body.thread_id).encode()
                ).hexdigest()
            },
            "recursion_limit": 40,
            "metadata": {"trace_id": task_id, "access_scope": scope["scope"]},
        }
        snapshot = await graph.aget_state(config)
        initial = (
            None
            if snapshot.next
            else {
                "request": body.model_dump(mode="json"),
                "scope": scope["scope"],
                "warnings": [],
                "results": {},
            }
        )
        # ponytail: 단일 프로세스의 SQLite 체크포인트를 사용하며 다중 worker 배포에는 공유 실행 잠금이 필요합니다.
        await execute(
            graph, harness, tools, config, initial, body.model_dump(mode="json"), scope["scope"]
        )
    except RunCancelled:
        ledger.keep(task_id, "result", {"status": "CANCELLED"})
    except Exception as error:
        try:
            await internal_request(
                task_id,
                "POST",
                "state",
                {
                    "status": "FAILED",
                    "error_code": "AI_EXECUTION_FAILED",
                    "error_message": "AI execution failed; local checkpoint is preserved",
                },
            )
        except Exception:
            pass
        ledger.event(task_id, "RUN_FAILED", error=type(error).__name__)
        row = ledger.row(task_id)
        ledger.keep(
            task_id,
            "result",
            {
                "status": "FAILED",
                "error": type(error).__name__,
                "report": json.loads(row["report"]) if row["report"] else None,
            },
        )
    finally:
        await harness.close()
        active.pop(task_id, None)
