"""TEST_DATABASE_URL을 지정한 전용 PostgreSQL에서 기존 백엔드와 AI를 연결합니다."""

# 기존 백엔드의 pytest fixture를 가져와 같은 마이그레이션과 인증 조건으로 검사합니다.
# ruff: noqa: F401, F811
import asyncio
import os
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

import httpx
import pytest
import uvicorn

pytest.importorskip("app.main")
pytest.importorskip("test_internal_api")
from app.main import app
from app.models import AnalysisReport, AnalysisTask, MemoVersion
from app.models.enums import AnalysisStatus
from app.repositories import AnalysisReportRepository
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from test_analysis import fake_model
from test_analysis_api import analysis_client, analysis_context
from test_auth_security import auth_settings
from test_domain import migrated_engine
from test_internal_api import KEY, internal_client, task

from disclosure_ai.entrypoints.worker import process_task
from disclosure_ai.services.business import BusinessError


@contextmanager
def serving(application):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(application, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(200):
            if server.started:
                break
            time.sleep(0.01)
        assert server.started
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@contextmanager
def backend_mcp(service, directory, *, live=False, **settings):
    repository = Path(__file__).resolve().parents[2]
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = dict(os.environ, **settings)
    env["PYTHONPATH"] = os.pathsep.join(
        str(repository / p) for p in [f"backend/mcp/{service}-mcp", "backend/shared"]
    )
    runner = Path(__file__).with_name("backend_mcp_runner.py")
    command = (
        [
            sys.executable,
            "-B",
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "error",
            "--no-access-log",
        ]
        if live
        else [sys.executable, "-B", str(runner), service, str(port)]
    )
    url = f"http://127.0.0.1:{port}"
    with (directory / (service + ".log")).open("w") as log:
        process = subprocess.Popen(
            command,
            cwd=directory,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(200):
                if process.poll() is not None:
                    raise AssertionError(f"{service} MCP exited before readiness")
                try:
                    if httpx.get(url + "/health", timeout=0.1, trust_env=False).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.05)
            else:
                raise AssertionError(f"{service} MCP readiness timeout")
            yield url + "/mcp"
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="전용 PostgreSQL 필요")
def test_worker_backend_report_retry_and_cancellation(
    internal_client, analysis_context, monkeypatch, tmp_path
):
    calls = []

    async def model(role, context, schema):
        calls.append(role)
        result = await fake_model(role, context, schema)
        if role == "base":
            result["selected"] = [
                {
                    "perspective_type": "FINANCE",
                    "selection_reason": "재무 영향 확인",
                    "question": "실적 영향",
                }
            ]
        return result

    with (
        serving(app) as backend,
        backend_mcp(
            "business", tmp_path, BUSINESS_API_BASE_URL=backend, INTERNAL_API_KEY=KEY
        ) as business,
        backend_mcp("external", tmp_path, OPENDART_API_KEY="0" * 40) as external,
        backend_mcp("rag", tmp_path, BUSINESS_MCP_URL=business, EXTERNAL_MCP_URL=external) as rag,
    ):
        monkeypatch.setenv("BUSINESS_MCP_URL", business)
        monkeypatch.setenv("EXTERNAL_MCP_URL", external)
        monkeypatch.setenv("RAG_MCP_URL", rag)
        task_id = task(analysis_context)
        state = tmp_path / "worker.sqlite"
        original_add = AnalysisReportRepository.add

        def fail(*args):
            raise OperationalError("test", {}, Exception("temporary DB failure"))

        monkeypatch.setattr(AnalysisReportRepository, "add", fail)
        with pytest.raises(BusinessError):
            asyncio.run(process_task(str(task_id), state, model))
        with analysis_context.factory() as db:
            assert db.get(AnalysisTask, task_id).status == AnalysisStatus.SAVE_FAILED
        assert calls == ["base", "perspective", "report", "output_check"]
        monkeypatch.setattr(AnalysisReportRepository, "add", original_add)
        result = asyncio.run(process_task(str(task_id), state, model))
        assert result["status"] == "COMPLETED_WITH_WARNINGS"
        assert calls == ["base", "perspective", "report", "output_check"]
        assert asyncio.run(process_task(str(task_id), state, model))["status"] == result["status"]
        with analysis_context.factory() as db:
            reports = list(
                db.scalars(select(AnalysisReport).where(AnalysisReport.analysis_task_id == task_id))
            )
            assert len(reports) == 1
            assert reports[0].report_json["results"]["FINANCE"]["status"] == "INSUFFICIENT_EVIDENCE"
            assert reports[0].report_json["request"]["company_name_snapshot"] == "검증기업"
            assert reports[0].report_json["sources"]
            assert reports[0].report_json["results"]["FINANCE"]["findings"] == ""
            memo = db.scalar(
                select(MemoVersion).where(
                    MemoVersion.memo_id == analysis_context.memos[0].id, MemoVersion.version == 3
                )
            )
            assert memo.content == "private memo body"
            assert UUID(result["report_id"]) == reports[0].id
        cancelled = task(analysis_context, AnalysisStatus.CANCELLED)
        assert asyncio.run(process_task(str(cancelled), state, model))["status"] == "CANCELLED"
        assert calls == ["base", "perspective", "report", "output_check"]

        # 시간 초과 후 초기 단계에 남은 작업도 모델 재호출 없이 저장 단계로 진행합니다.
        import json
        import time

        from disclosure_ai.harness.ledger import Ledger
        from disclosure_ai.harness.runtime import Harness
        from disclosure_ai.services.tools import Tools
        from disclosure_ai.workflow.execution import retry_save

        early = task(analysis_context)
        ledger = Ledger(str(state))
        try:
            ledger.begin(str(early), "early", started=time.time() - 121)
            body = json.loads(ledger.row(str(task_id))["report"])
            body["report_json"]["request"]["analysis_task_id"] = str(early)
            ledger.keep(str(early), "report", body)
            h = Harness(str(early), ledger)
            saved = asyncio.run(retry_save(h, Tools(""), body))
            assert saved["status"] == "COMPLETED_WITH_WARNINGS"
            repeated = asyncio.run(retry_save(h, Tools(""), body))
            assert repeated["report_id"] == saved["report_id"]
            assert ledger.row(str(early))["turns"] == 0
        finally:
            ledger.db.close()
