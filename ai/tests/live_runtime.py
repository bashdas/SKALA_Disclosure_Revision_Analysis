"""전용 DB와 RabbitMQ, 실제 외부 API를 명시적으로 연결해 검사합니다."""

# ruff: noqa: F401, F811
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import UUID

import pytest
from app.core.security import create_access_token
from app.infrastructure.analysis_queue import RabbitMQAnalysisProducer
from app.models import AnalysisReport, AnalysisTask, Filing, FilingVersion, MemoVersion
from app.models.enums import AnalysisStatus
from pydantic import SecretStr
from sqlalchemy import delete, select, text, update
from test_analysis_api import request
from test_business_integration import (
    KEY,
    analysis_client,
    analysis_context,
    app,
    auth_settings,
    backend_mcp,
    internal_client,
    migrated_engine,
    serving,
)

from disclosure_ai.services.business import mcp_call

MEMO = "미로바 글로벌 지속가능 주식형 펀드는 2024년 12월 31일 기준 순자산의 97.32%가 지속가능한 투자목표와 부합합니다.\n기업 관여 활동 사례는 2024년 Microsoft와의 소통입니다.\n요약 재무내용과 운용자산 규모의 기준일은 2024년 12월 31일입니다."


@pytest.mark.skipif(os.environ.get("AI_LIVE_RUNTIME") != "1", reason="실제 서비스 명시 실행 필요")
def test_live_queue_to_report(internal_client, analysis_context, tmp_path):
    settings = analysis_context.settings
    settings.rabbitmq_url = SecretStr(os.environ["RABBITMQ_URL"])
    # 분석할 기존 주장이 있어야 수정 제안의 품질을 검증할 수 있습니다.
    with analysis_context.factory() as db:
        memo = db.scalar(
            select(MemoVersion).where(
                MemoVersion.memo_id == analysis_context.memos[0].id, MemoVersion.version == 3
            )
        )
        memo.content = MEMO
        db.commit()
    producer = RabbitMQAnalysisProducer(settings)
    analysis_context.producer = producer
    try:
        producer.check_health()
        with (
            serving(app) as backend,
            backend_mcp(
                "business", tmp_path, live=True, BUSINESS_API_BASE_URL=backend, INTERNAL_API_KEY=KEY
            ) as business,
            backend_mcp("external", tmp_path, live=True) as external,
            backend_mcp(
                "rag", tmp_path, live=True, BUSINESS_MCP_URL=business, EXTERNAL_MCP_URL=external
            ) as rag,
            (tmp_path / "worker.log").open("w") as log,
        ):
            settings.external_mcp_url = external
            registered = internal_client.post(
                "/api/v1/filings",
                json={"receipt_no": "20261020000245"},
                headers={
                    "Authorization": "Bearer "
                    + create_access_token(analysis_context.users[0], settings=settings)
                },
            )
            assert registered.status_code == 200, registered.text
            assert registered.json()["is_correction"] is True
            environment = dict(
                os.environ, BUSINESS_MCP_URL=business, EXTERNAL_MCP_URL=external, RAG_MCP_URL=rag
            )
            worker = subprocess.Popen(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "disclosure_ai.entrypoints.worker",
                    "--state",
                    str(tmp_path / "worker.sqlite"),
                ],
                env=environment,
                cwd=tmp_path,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                response = request(internal_client, analysis_context, receipt="20261020000245")
                assert response.status_code == 202
                task_id = UUID(response.json()["task_id"])
                deadline = time.monotonic() + 150
                while time.monotonic() < deadline:
                    assert worker.poll() is None, "AI worker exited"
                    with analysis_context.factory() as db:
                        status = db.get(AnalysisTask, task_id).status
                    if status in {
                        AnalysisStatus.COMPLETED,
                        AnalysisStatus.COMPLETED_WITH_WARNINGS,
                        AnalysisStatus.FAILED,
                        AnalysisStatus.SAVE_FAILED,
                    }:
                        break
                    time.sleep(0.25)
                assert status in {
                    AnalysisStatus.COMPLETED,
                    AnalysisStatus.COMPLETED_WITH_WARNINGS,
                }, status
                with analysis_context.factory() as db:
                    reports = list(
                        db.scalars(
                            select(AnalysisReport).where(AnalysisReport.analysis_task_id == task_id)
                        )
                    )
                    assert len(reports) == 1
                    report = reports[0].report_json
                    assert report["request"]["company_name_snapshot"] == "미로바펀즈"
                    assert report["base"] is not None
                    assert report["sections"]["correction"]
                    assert report["base"]["proposals"]
                    assert report["sections"]["memo_impact"]
                    assert report["sections"]["suggestions"]
                    assert report["sections"]["summary"]
                    assert report["sections"]["future_impacts"]
                    assert len(report["corrections"]) == 10
                    assert all(p["before_text"] in MEMO for p in report["base"]["proposals"])
                    covered = "\n".join(p["before_text"] for p in report["base"]["proposals"])
                    assert all(sentence in covered for sentence in MEMO.splitlines())
                    assert all(
                        r["status"] == "COMPLETED" or not r["findings"]
                        for r in report["results"].values()
                    )
                    (tmp_path / "report.md").write_text(reports[0].content)
                    memo = db.scalar(
                        select(MemoVersion).where(
                            MemoVersion.memo_id == analysis_context.memos[0].id,
                            MemoVersion.version == 3,
                        )
                    )
                    assert memo.content == MEMO
                    manifest = (
                        db.execute(
                            text("SELECT * FROM rag.analysis_indexes WHERE task_id=:id"),
                            {"id": task_id},
                        )
                        .mappings()
                        .one()
                    )
                    for key in ("memo_document_id", "disclosure_document_id"):
                        count = db.execute(
                            text(
                                "SELECT count(*) FROM rag.chunks WHERE document_id=:id AND vector_dims(embedding)=1536"
                            ),
                            {"id": manifest[key]},
                        ).scalar_one()
                        assert count > 0
                previous = os.environ.get("RAG_MCP_URL")
                os.environ["RAG_MCP_URL"] = rag
                try:
                    evidence = asyncio.run(
                        mcp_call(
                            "RAG",
                            "search_evidence",
                            {"task_id": str(task_id), "query": "정정 내용", "top_k": 5},
                        )
                    )
                finally:
                    if previous is None:
                        os.environ.pop("RAG_MCP_URL", None)
                    else:
                        os.environ["RAG_MCP_URL"] = previous
                assert not evidence.get("error"), evidence.get("error")
                print("Live queue, MCP, OpenDART, model, pgvector and report persistence verified")
            finally:
                worker.terminate()
                try:
                    worker.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait(timeout=5)
    finally:
        producer.close()
        with analysis_context.factory() as db:
            user_id = analysis_context.users[0].id
            db.execute(
                update(AnalysisTask)
                .where(AnalysisTask.requested_by == user_id)
                .values(filing_id=None)
            )
            receipts = select(AnalysisTask.disclosure_receipt_no).where(AnalysisTask.requested_by == user_id)
            filing_ids = select(Filing.id).where(Filing.receipt_no.in_(receipts))
            db.execute(delete(FilingVersion).where(FilingVersion.filing_id.in_(filing_ids)))
            db.execute(delete(Filing).where(Filing.id.in_(filing_ids)))
            db.commit()
