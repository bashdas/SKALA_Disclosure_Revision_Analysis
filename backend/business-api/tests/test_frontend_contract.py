from datetime import datetime, timezone
from uuid import UUID

import pytest
from app.core.security import create_access_token
from app.models import AnalysisReport, MemoVersion
from test_analysis_api import analysis_context, analysis_client, request
from test_auth_security import auth_settings
from test_domain import migrated_engine


@pytest.mark.postgres
def test_public_workspace_contract(analysis_client, analysis_context):
    context = analysis_context
    headers = {"Authorization": "Bearer " + create_access_token(context.users[0], settings=context.settings)}
    other = {"Authorization": "Bearer " + create_access_token(context.users[1], settings=context.settings)}
    with context.factory() as db:
        db.add(MemoVersion(memo_id=context.memos[0].id, version=1, content="older version", created_by=context.users[0].id))
        db.commit()
    response = request(analysis_client, context, memo_version=1)
    assert response.status_code == 202
    task_id = response.json()["task_id"]
    path = f"/api/v1/analyses/{task_id}"
    assert analysis_client.get("/api/v1/users/me", headers=headers).json()["id"] == str(context.users[0].id)
    rows = analysis_client.get("/api/v1/analyses", headers=headers).json()
    assert len(rows) == 1 and rows[0]["base_memo_version"] == 1
    assert analysis_client.get("/api/v1/analyses", headers=other).json() == rows
    assert analysis_client.get(path + "/perspectives", headers=headers).json() == []
    assert analysis_client.get(path + "/report", headers=headers).json() is None
    with context.factory() as db:
        db.add(AnalysisReport(analysis_task_id=UUID(task_id), content="stored report", report_json={"sources": []}, generated_at=datetime.now(timezone.utc), saved_at=datetime.now(timezone.utc)))
        db.commit()
    assert analysis_client.get(path + "/report", headers=headers).json()["content"] == "stored report"
    for suffix in ("/report", "/perspectives"):
        assert analysis_client.get(path + suffix, headers=other).json() == analysis_client.get(path + suffix, headers=headers).json()
        assert analysis_client.get(path + suffix).status_code == 401
    assert request(analysis_client, context, memo_version=99).status_code == 404
    assert request(analysis_client, context, memo_version=0).status_code == 422
    assert analysis_client.get("/api/v1/analyses?limit=101", headers=headers).status_code == 422
