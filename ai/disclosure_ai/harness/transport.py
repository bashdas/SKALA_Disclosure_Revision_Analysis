import asyncio
import time
from contextlib import contextmanager
from contextvars import ContextVar

current_run = ContextVar("current_run", default=None)


@contextmanager
def bind(harness):
    token = current_run.set(harness)
    try:
        yield
    finally:
        current_run.reset(token)


async def invoke(name, operation, *, window_seconds=None):
    harness = current_run.get()
    deadline = time.monotonic() + window_seconds if window_seconds is not None else None
    result = {"error": "LIMIT_REACHED"}
    # 상태 동기화는 조회 캐시를 사용하지 않고 각 전송의 재시도와 시간을 제한합니다.
    for attempt in range(3):
        remaining = (
            deadline - time.monotonic()
            if deadline is not None
            else (harness.remaining(True) if harness else 10)
        )
        if remaining <= 0:
            break
        try:
            async with asyncio.timeout(min(10, remaining)):
                result = await operation()
        except TimeoutError:
            result = {"error": "MCP_UNAVAILABLE", "retryable": True}
        if harness:
            harness.ledger.event(
                harness.task_id,
                "CONTROL_CALL",
                tool=name,
                attempt=attempt + 1,
                error=result.get("error"),
            )
        if not result.get("retryable") or not result.get("error"):
            break
    return result
