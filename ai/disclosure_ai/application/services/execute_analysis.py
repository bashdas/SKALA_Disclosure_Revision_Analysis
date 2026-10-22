import fcntl
import hashlib
import json
import os
import time
from pathlib import Path
from uuid import UUID

from disclosure_ai.application.commands.analyze_disclosure import AnalysisRequest
from disclosure_ai.application.services.analysis_service import execute, retry_save
from disclosure_ai.domain.errors import BusinessError, RunCancelled
from disclosure_ai.ports.execution import ExecutionDependencies


async def process_task(
    task_id: str, state: Path, call_model=None, *, dependencies: ExecutionDependencies
) -> dict:
    internal_request = dependencies.internal_request
    fixed_request = dependencies.fixed_request
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
        ledger = dependencies.repository(str(state))
        harness = None
        tools = dependencies.tools("")
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
                harness = dependencies.harness(task_id, ledger, call_model)
                result = await retry_save(harness, tools, json.loads(row["report"]))
                if result.get("error"):
                    raise BusinessError(result["error"], result.get("retryable", False))
                return result
            if context["status"] in {"SAVING", "SAVE_FAILED"}:
                raise BusinessError("LOCAL_REPORT_MISSING")
            harness = dependencies.harness(task_id, ledger, call_model)
            async with dependencies.checkpointer(state) as saver:
                graph = dependencies.workflow(harness, tools, saver)
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
