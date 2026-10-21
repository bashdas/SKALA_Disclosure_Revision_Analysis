from typing import get_args

import pytest

from disclosure_ai.schemas import Impact, Perspective


def test_existing_backend_contract():
    pytest.importorskip("app.main")
    from app.main import app
    from app.models.enums import ImpactType, PerspectiveType
    from app.schemas.memo import MemoVersionDetailResponse

    schema = app.openapi()
    assert "/api/v1/memos/{memo_id}/versions/{version}" in schema["paths"]
    assert {"content", "memo_id", "version"} <= MemoVersionDetailResponse.model_fields.keys()
    assert set(get_args(Perspective)) == {p.value for p in PerspectiveType}
    assert set(get_args(Impact)) == {p.value for p in ImpactType}
    assert "/internal/ai/authorize" not in schema["paths"]

    from app.schemas.internal import (
        InternalStateRequest,
        PerspectiveCreateRequest,
        ReportSaveRequest,
    )

    assert "/internal/analyses/{task_id}/context" in schema["paths"]
    assert "/internal/analyses/{task_id}/report" in schema["paths"]
    ReportSaveRequest.model_validate(
        {"content": "보고서", "report": {"sources": []}, "has_warnings": False}
    )
    PerspectiveCreateRequest.model_validate(
        {
            "perspective_type": "FINANCE",
            "selection_reason": "정정 영향",
            "question": "실적 영향",
            "max_tool_calls": 3,
            "timeout_seconds": 90,
        }
    )
    InternalStateRequest.model_validate({"status": "RUNNING"})
