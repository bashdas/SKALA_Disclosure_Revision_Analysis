import os
from pathlib import Path

import tiktoken

from disclosure_ai.analysis.reporting.grounding_review import review_output
from disclosure_ai.ports.run_repository import RunRepository
from disclosure_ai.runtime import tool_executor as lookup
from disclosure_ai.runtime.budget import RunBudget
from disclosure_ai.runtime.model_executor import ModelExecutor


class Harness(RunBudget, ModelExecutor):
    def __init__(self, task_id: str, ledger: RunRepository, call_model=None, *, model_gateway=None):
        self.task_id = task_id
        self.ledger = ledger
        self.call_model = call_model
        self.model_gateway = model_gateway
        self.inflight = {}
        self.client = None
        self.guard = None
        # 인코딩 파일도 실행 산출물 경로에 보관합니다.
        os.environ.setdefault(
            "TIKTOKEN_CACHE_DIR",
            str(Path(os.environ.get("XDG_CACHE_HOME", "outputs/cache")) / "tiktoken"),
        )
        self.encoding = tiktoken.get_encoding("o200k_base")

    async def review_output(
        self, payload: dict, *, grounding=False, corrections=()
    ) -> tuple[dict, list[str]]:
        return await review_output(self, payload, grounding=grounding, corrections=corrections)

    async def tool(self, name, args, invoke, *, report=False, scope=""):
        return await lookup.call(self, name, args, invoke, report=report, scope=scope)
