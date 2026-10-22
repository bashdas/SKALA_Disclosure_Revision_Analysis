import asyncio
import hashlib
import json
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from disclosure_ai.application.services.analysis_service import retry_save as save_again
from disclosure_ai.application.services.http_analysis import run_http_analysis
from disclosure_ai.infrastructure.mcp.client import internal_request
from disclosure_ai.infrastructure.mcp.tool_gateway import Tools
from disclosure_ai.infrastructure.persistence.sqlite_run_repository import Ledger
from disclosure_ai.presentation.http.schemas.requests import AnalysisRequest
from disclosure_ai.runtime.harness import Harness
from disclosure_ai.workflow.graph import AnalysisGraph


@asynccontextmanager
async def lifespan(app: FastAPI):
    path = os.environ.get("AI_STATE_PATH", "outputs/ai-state.sqlite")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    os.chmod(Path(path).parent, 0o700)
    app.state.ledger = Ledger(path)
    app.state.active = {}
    async with AsyncSqliteSaver.from_conn_string(path + ".checkpoints") as checkpointer:
        app.state.checkpointer = checkpointer
        yield
        pending = list(app.state.active.values())
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    app.state.ledger.db.close()


app = FastAPI(title="Disclosure AI", lifespan=lifespan)


def internal_auth(x_ai_token: Annotated[str | None, Header()] = None):
    expected = os.environ.get("AI_INTERNAL_TOKEN", "")
    if len(expected) < 32:
        raise HTTPException(503, "AI 내부 인증 설정이 필요합니다.")
    if not x_ai_token or not secrets.compare_digest(x_ai_token, expected):
        raise HTTPException(403, "내부 접근 권한이 없습니다.")


Internal = Annotated[None, Depends(internal_auth)]
Authorization = Annotated[str, Header()]


@app.get("/health")
def health():
    return {"status": "ok", "service": "disclosure-ai"}


async def authorized(body: AnalysisRequest, authorization: str):
    tools = Tools(authorization)
    try:
        scope = await tools.authorize(body.model_dump(mode="json"))
    except Exception as error:
        raise HTTPException(403, "작업 접근 권한 또는 고정 입력을 확인하지 못했습니다.") from error
    return tools, scope


def checked_row(body: AnalysisRequest) -> dict:
    try:
        row = app.state.ledger.row(str(body.analysis_task_id))
    except TypeError as error:
        raise HTTPException(404, "작업이 없습니다.") from error
    fingerprint = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    if row["fingerprint"] != fingerprint:
        raise HTTPException(409, "작업 ID와 고정 입력이 일치하지 않습니다.")
    return row


async def run(body: AnalysisRequest, tools: Tools, scope: dict):
    await run_http_analysis(
        body,
        tools,
        scope,
        ledger=app.state.ledger,
        checkpointer=app.state.checkpointer,
        active=app.state.active,
        harness_factory=Harness,
        graph_factory=AnalysisGraph,
        internal_request=internal_request,
    )


@app.post("/internal/analyses", status_code=202)
async def start(body: AnalysisRequest, authorization: Authorization, _internal: Internal):
    tools, scope = await authorized(body, authorization)
    task_id = str(body.analysis_task_id)
    fingerprint = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    try:
        input_key = f"{body.memo_id}:{body.base_memo_version}:{body.disclosure_receipt_no}"
        app.state.ledger.begin(task_id, fingerprint, input_key)
    except ValueError as error:
        raise HTTPException(409, "작업 ID에 다른 입력을 사용할 수 없습니다.") from error
    if task_id not in app.state.active:
        row = app.state.ledger.row(task_id)
        if row["result"] and json.loads(row["result"]).get("status") != "FAILED":
            return {"analysis_task_id": task_id, "result": json.loads(row["result"])}
        app.state.active[task_id] = asyncio.create_task(run(body, tools, scope))
    return {"analysis_task_id": task_id, "status": "RUNNING"}


@app.post("/internal/analyses/{task_id}/retry-save")
async def retry_save(
    task_id: UUID, body: AnalysisRequest, authorization: Authorization, _internal: Internal
):
    if task_id != body.analysis_task_id:
        raise HTTPException(409, "작업 ID가 일치하지 않습니다.")
    tools, _ = await authorized(body, authorization)
    if str(task_id) in app.state.active:
        raise HTTPException(409, "분석 실행 중입니다.")
    try:
        row = checked_row(body)
    except TypeError as error:
        raise HTTPException(404, "보존한 보고서가 없습니다.") from error
    if not row["report"]:
        raise HTTPException(409, "생성된 보고서가 없습니다.")
    harness = Harness(str(task_id), app.state.ledger)
    try:
        result = await save_again(harness, tools, json.loads(row["report"]))
    finally:
        await harness.close()
    return {**result, "report": json.loads(row["report"])}


@app.post("/internal/analyses/{task_id}/result")
async def result(
    task_id: UUID, body: AnalysisRequest, authorization: Authorization, _internal: Internal
):
    if task_id != body.analysis_task_id:
        raise HTTPException(409, "작업 ID가 일치하지 않습니다.")
    await authorized(body, authorization)
    try:
        row = checked_row(body)
    except TypeError as error:
        raise HTTPException(404, "작업이 없습니다.") from error
    return {
        "result": json.loads(row["result"]) if row["result"] else None,
        "turns": row["turns"],
        "reserved_tokens": row["tokens"],
    }


@app.post("/internal/analyses/{task_id}/events")
async def events(
    task_id: UUID,
    body: AnalysisRequest,
    authorization: Authorization,
    _internal: Internal,
    after: Annotated[int, Query(ge=0)] = 0,
):
    if task_id != body.analysis_task_id:
        raise HTTPException(409, "작업 ID가 일치하지 않습니다.")
    await authorized(body, authorization)
    checked_row(body)

    async def stream():
        cursor = after
        while True:
            rows = app.state.ledger.events(str(task_id), cursor)
            for row in rows:
                cursor = row["id"]
                yield f"id: {cursor}\nevent: {row['kind']}\ndata: {row['payload']}\n\n"
            if str(task_id) not in app.state.active and len(rows) < 100:
                break
            await asyncio.sleep(0.25)

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )
