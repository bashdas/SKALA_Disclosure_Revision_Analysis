"""백엔드 연결 전 고정 메모와 공개 공시로 같은 분석 그래프를 실행합니다."""

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import Field

from disclosure_ai.application.commands.analyze_disclosure import AnalysisRequest
from disclosure_ai.application.services.analysis_service import execute
from disclosure_ai.domain.models.base import Model
from disclosure_ai.infrastructure.documents.parser import parse_filing
from disclosure_ai.infrastructure.persistence.sqlite_run_repository import Ledger
from disclosure_ai.runtime.harness import Harness
from disclosure_ai.workflow.graph import AnalysisGraph


class Snapshot(Model):
    request: AnalysisRequest
    memo_text: str = Field(min_length=1, max_length=100000)


class LocalTools:
    def __init__(self, snapshot: Snapshot, filing: bytes):
        self.snapshot = snapshot
        self.filing = filing

    async def call(self, name: str, args: dict) -> dict:
        request = self.snapshot.request
        if name in {"business_get_memo", "disclosure_get_document"}:
            if (
                args.get("task_id") != str(request.analysis_task_id)
                or args.get("memo_id") != str(request.memo_id)
                or args.get("version") != request.base_memo_version
            ):
                return {"error": "SNAPSHOT_MISMATCH"}
        if name == "business_get_memo":
            return {
                "document_id": f"memo:{request.memo_id}:v{request.base_memo_version}",
                "memo_id": str(request.memo_id),
                "version": request.base_memo_version,
                "text": self.snapshot.memo_text,
            }
        if name == "disclosure_get_document":
            if args.get("receipt_no") != request.disclosure_receipt_no:
                return {"error": "SNAPSHOT_MISMATCH"}
            return parse_filing(self.filing, request.disclosure_receipt_no)
        if name == "business_save_report":
            # 그래프가 먼저 저장한 로컬 보고서를 반환하고 업무 DB 저장 대기를 표시합니다.
            return {
                "status": "LOCAL_SAVED",
                "report_id": str(request.analysis_task_id),
                "storage": "local",
                "business_save_status": "PENDING_BACKEND",
            }
        if name in {"financial", "academic"}:
            return {"error": "BACKEND_TOOL_REQUIRED", "tool": name}
        return {"error": "TOOL_NOT_AVAILABLE"}


async def analyze(snapshot: Snapshot, state: Path, filing: bytes, call_model=None):
    task_id = str(snapshot.request.analysis_task_id)
    state.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # 같은 상태 저장소의 동시 실행은 입력 고정과 조회 횟수를 깨뜨릴 수 있습니다.
    with state.with_suffix(state.suffix + ".lock").open("a") as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        ledger = Ledger(str(state))
        harness = None
        try:
            fingerprint = hashlib.sha256(
                snapshot.model_dump_json().encode() + hashlib.sha256(filing).digest()
            ).hexdigest()
            request = snapshot.request.model_dump(mode="json")
            scope = f"local:{request['memo_id']}:{request['base_memo_version']}"
            ledger.begin(task_id, fingerprint, scope + ":" + request["disclosure_receipt_no"])
            row = ledger.row(task_id)
            if row["result"]:
                return json.loads(row["result"])
            harness = Harness(task_id, ledger, call_model)
            async with AsyncSqliteSaver.from_conn_string(str(state) + ".checkpoints") as saver:
                tools = LocalTools(snapshot, filing)
                graph = AnalysisGraph(harness, tools, saver).graph
                config = {
                    "configurable": {"thread_id": task_id + ":" + fingerprint},
                    "recursion_limit": 40,
                }
                checkpoint = await graph.aget_state(config)
                initial = (
                    None
                    if checkpoint.next
                    else {
                        "request": request,
                        "scope": scope,
                        "warnings": [],
                        "results": {},
                    }
                )
                # 재개 시에도 최초 실행부터 누적된 시간과 호출 예산을 사용합니다.
                result = await execute(graph, harness, tools, config, initial, request, scope)
                return result["output"]
        finally:
            if harness:
                await harness.close()
            ledger.db.close()


def main():
    parser = argparse.ArgumentParser(
        description="고정 메모와 공시를 분석하고 AI 로컬 보고서를 보존합니다."
    )
    parser.add_argument("--input", type=Path, required=True, help="request와 memo_text를 담은 JSON")
    parser.add_argument("--state", type=Path, required=True, help="AI 상태를 보존할 SQLite 파일")
    parser.add_argument(
        "--filing", type=Path, required=True, help="백엔드 등에서 확보한 OpenDART ZIP"
    )
    args = parser.parse_args()
    try:
        if args.input.stat().st_size > 1024 * 1024:
            raise ValueError("INPUT_TOO_LARGE")
        snapshot = Snapshot.model_validate_json(args.input.read_bytes())
        if args.filing.stat().st_size > 20 * 1024 * 1024:
            raise ValueError("FILING_TOO_LARGE")
        filing = args.filing.read_bytes()
        result = asyncio.run(analyze(snapshot, args.state, filing))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as error:
        # 검증 오류와 HTTP 예외의 원문에는 메모나 인증키가 포함될 수 있습니다.
        print(json.dumps({"status": "FAILED", "error": type(error).__name__}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
