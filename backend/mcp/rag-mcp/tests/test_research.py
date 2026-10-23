import asyncio
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from app.errors import RagError
from app.research import Report, report_chunks, search_reports


def test_report_chunks_preserve_page_and_original_text():
    report = Report(report_id=uuid4(), version=2, title="Internal report", corp_code="00126478",
        company_name="Company", published_at="2026-01-01", source_file="report.pdf",
        text="[1쪽]\nA row\nB row", pages=[{"page": 1, "text": "A row\nB row"}], content_hash="a" * 64)
    chunks = report_chunks(report, size=6)
    assert [c.text for c in chunks] == ["A row\n", "B row"]
    assert chunks[1].metadata["location"] == "page:1:chars:6-11"
    assert all(c.text in report.text for c in chunks)


def test_report_search_rejects_wrong_task_before_embedding():
    task_id = uuid4()
    service = SimpleNamespace(context=AsyncMock(return_value=SimpleNamespace()),
        sources=SimpleNamespace(get_research_reports=AsyncMock(return_value={
            "task_id": str(uuid4()), "reports": []})))
    with pytest.raises(RagError, match="조회 범위"):
        asyncio.run(search_reports(service, task_id, "query", 5))
