from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from threading import Barrier
from unittest.mock import patch
from uuid import UUID

import pytest
from app.core.security import create_access_token
from app.domain.memo_upload_exceptions import MemoVersionConflict
from app.models import Memo, MemoVersion
from app.repositories import MemoRepository
from app.services.memo import MemoService
from sqlalchemy import func, select
from test_auth_security import auth_settings  # noqa: F401
from test_domain import migrated_engine  # noqa: F401
from test_memo_upload import post, upload_client, upload_context  # noqa: F401


@pytest.mark.postgres
def test_shared_edit_preserves_versions_and_rejects_stale_writes(request):
    client = request.getfixturevalue("upload_client")
    context = request.getfixturevalue("upload_context")
    memo_id = post(client, b"original").json()["id"]
    path = f"/api/v1/memos/{memo_id}/versions"
    content = "수정한 메모입니다."
    response = client.post(path, json={"content": content, "base_version": 1})
    assert response.status_code == 200 and response.json()["current_version"] == 2
    assert client.get(path + "/1").json()["content"] == "original"
    latest = client.get(path + "/2").json()
    assert latest["content"] == content
    assert latest["content_hash"] == sha256(content.encode()).hexdigest()
    assert latest["size_bytes"] == len(content.encode())
    assert latest["created_by"] == str(context.users[0].id)
    assert client.post(path, json={"content": "stale", "base_version": 1}).status_code == 409
    assert client.post(path, json={"content": content, "base_version": 2}).json()["current_version"] == 2
    assert len(client.get(path).json()) == 2
    other = context.users[1]
    headers = {"Authorization": "Bearer " + create_access_token(other, settings=context.settings)}
    assert client.post(path, headers=headers, json={"content": "colleague update", "base_version": 2}).json()["current_version"] == 3
    assert client.get(path + "/3").json()["created_by"] == str(other.id)
    assert client.delete(f"/api/v1/memos/{memo_id}").status_code == 204
    assert client.post(path, json={"content": "deleted", "base_version": 2}).status_code == 404


@pytest.mark.postgres
@pytest.mark.parametrize("content,status", [("  ", 400), ("a\x00b", 400), ("한" * 86, 413)])
def test_invalid_edit_leaves_original_unchanged(request, content, status):
    client = request.getfixturevalue("upload_client")
    memo_id = post(client, b"original").json()["id"]
    path = f"/api/v1/memos/{memo_id}/versions"
    assert client.post(path, json={"content": content, "base_version": 1}).status_code == status
    assert len(client.get(path).json()) == 1
    assert client.get(path + "/1").json()["content"] == "original"


@pytest.mark.postgres
def test_concurrent_edit_and_rollback_are_atomic(request):
    client = request.getfixturevalue("upload_client")
    context = request.getfixturevalue("upload_context")
    memo_id = UUID(post(client, b"original").json()["id"])
    barrier = Barrier(2)
    user = context.users[0]
    def edit(content):
        with context.factory() as session:
            barrier.wait(timeout=5)
            try:
                MemoService(MemoRepository(session)).edit(memo_id, user.id, content, 1)
                return "saved"
            except MemoVersionConflict:
                return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(edit, ["first", "second"])) == ["conflict", "saved"]
    with context.factory() as session, patch.object(session, "commit", side_effect=RuntimeError("commit failed")), pytest.raises(RuntimeError):
        MemoService(MemoRepository(session)).edit(memo_id, user.id, "rollback", 2)
    with context.factory() as session:
        assert session.get(Memo, memo_id).current_version == 2
        assert session.scalar(select(func.count()).select_from(MemoVersion).where(MemoVersion.memo_id == memo_id)) == 2
