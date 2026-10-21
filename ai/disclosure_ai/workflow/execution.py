import asyncio
import json
from types import SimpleNamespace

from disclosure_ai.harness.transport import bind
from disclosure_ai.services.business import RunCancelled
from disclosure_ai.workflow import reporting


def checkpoint_values(snapshot, fallback):
    state = {**fallback, **getattr(snapshot, "values", {})}
    for task in getattr(snapshot, "tasks", ()):
        nested = getattr(task, "state", None)
        if hasattr(nested, "values"):
            state.update(checkpoint_values(nested, state))
    return state


async def execute(graph, harness, tools, config, initial, request, scope):
    with bind(harness):
        try:
            async with asyncio.timeout(max(0.001, harness.remaining(True))):
                return await graph.ainvoke(initial, config)
        except RunCancelled:
            raise
        except Exception as error:
            harness.ledger.event(harness.task_id, "RUN_RECOVERY", error=type(error).__name__)
            state = {"request": request, "scope": scope, "warnings": [], "results": {}}
            try:
                snapshot = await graph.aget_state(config, subgraphs=True)
                state = checkpoint_values(snapshot, state)
            except Exception:
                pass
            run = SimpleNamespace(h=harness, tools=tools)
            row = harness.ledger.row(harness.task_id)
            body = (
                json.loads(row["report"])
                if row["report"]
                else reporting.emergency(run, state, error)
            )
            state["report"] = body
            failure = "TIME_LIMIT"
            if harness.remaining(True) > 0:
                try:
                    saved = await reporting.save(run, state)
                    return {**state, **saved}
                except RunCancelled:
                    raise
                except Exception as save_error:
                    failure = type(save_error).__name__
            result = {"status": "SAVE_FAILED", "error": failure, "report": body}
            harness.ledger.keep(harness.task_id, "result", result)
            saved = {"output": result}
            return {**state, **saved}


async def retry_save(harness, tools, report):
    from disclosure_ai.harness.transport import invoke

    # 재저장은 별도 사용자 작업이며 같은 작업 ID의 보고서만 10초 안에서 다시 저장합니다.
    async def save():
        # 내부 상태 전송도 바깥의 재저장 제한 시간에 포함합니다.
        with bind(None):
            return await tools.call(
                "business_save_report", {"task_id": harness.task_id, "report": report}
            )

    try:
        with bind(harness):
            result = await invoke("business_save_report", save, window_seconds=10)
    except RunCancelled:
        raise
    except Exception as error:
        result = {"error": type(error).__name__}
    if result.get("error"):
        result = {**result, "status": "SAVE_FAILED", "report": report}
    harness.ledger.keep(harness.task_id, "result", result)
    return result
