from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import create_access_token
from app.domain.memo_upload_exceptions import InvalidMemoFilename, MemoFileTooLarge
from app.main import app
from app.models import Memo, MemoVersion, Organization, User
from app.models.enums import UserRole
from app.repositories import MemoRepository
from app.services.memo import MemoService
from app.services.memo_text_extractor import PlainTextMemoExtractor
from test_auth_security import auth_settings
from test_domain import migrated_engine


@pytest.fixture
def upload_context(migrated_engine, auth_settings):
    # Committed setup + independent request sessions verifies real commit visibility,
    # unlike a Session bound to a test's external rollback-only transaction.
    auth_settings.memo_upload_max_bytes = 256
    factory = sessionmaker(migrated_engine, expire_on_commit=False, autoflush=False)
    with factory() as session:
        organizations = [Organization(name="Upload organization A"), Organization(name="Upload organization B")]
        session.add_all(organizations)
        session.flush()
        users = [User(organization_id=org.id, email=f"{uuid4()}@example.test", password_hash="unused-for-bearer-test", role=role) for org, role in zip(organizations, [UserRole.RA, UserRole.ANALYST])]
        session.add_all(users)
        session.commit()
    result = SimpleNamespace(engine=migrated_engine, factory=factory, users=users, organizations=organizations, settings=auth_settings)
    try:
        yield result
    finally:
        organization_ids = [org.id for org in organizations]
        with factory() as session:
            memo_ids = select(Memo.id).where(Memo.organization_id.in_(organization_ids))
            session.execute(delete(MemoVersion).where(MemoVersion.memo_id.in_(memo_ids)))
            session.execute(delete(Memo).where(Memo.organization_id.in_(organization_ids)))
            session.execute(delete(User).where(User.id.in_([user.id for user in users])))
            session.execute(delete(Organization).where(Organization.id.in_(organization_ids)))
            session.commit()


@pytest.fixture
def upload_client(upload_context):
    previous = app.dependency_overrides.copy()

    def session_override():
        with upload_context.factory() as session:
            yield session

    app.dependency_overrides[get_db] = session_override
    app.dependency_overrides[get_settings] = lambda: upload_context.settings
    headers = {"Authorization": "Bearer " + create_access_token(upload_context.users[0], settings=upload_context.settings)}
    try:
        with TestClient(app, headers=headers) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def post(client, raw=b"Original memo content", name="company_review.txt", mime="text/plain", **fields):
    return client.post("/api/v1/memos", files={"file": (name, raw, mime)}, data=fields)


def assert_empty(context):
    with context.factory() as session:
        assert session.scalar(select(func.count()).select_from(Memo).where(Memo.organization_id.in_([org.id for org in context.organizations]))) == 0


@pytest.mark.postgres
@pytest.mark.parametrize("user_index", [0, 1])
def test_upload_roles_and_atomic_v1_persistence(upload_client, upload_context, user_index):
    user = upload_context.users[user_index]
    upload_client.headers["Authorization"] = "Bearer " + create_access_token(user, settings=upload_context.settings)
    raw = "기업분석 원문\nKeep whitespace.\n".encode("utf-8")
    response = post(upload_client, raw, "기업명_검토.txt")
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "기업명_검토"
    assert body["company_name"] is None
    assert body["current_version"] == 1
    assert body["original_filename"] == "기업명_검토.txt"
    assert body["content_type"] == "text/plain"
    assert body["size_bytes"] == len(raw)
    assert body["content_hash"] == sha256(raw).hexdigest()
    assert "organization_id" not in body and "content" not in body
    # A separate DB session sees both committed rows after the HTTP response.
    with upload_context.factory() as session:
        memo = session.get(Memo, UUID(body["id"]))
        version = session.scalar(select(MemoVersion).where(MemoVersion.memo_id == memo.id))
        assert memo.organization_id == user.organization_id
        assert memo.company_name is None and memo.current_version == 1
        assert version.version == 1 and version.created_by == user.id
        assert version.content == raw.decode("utf-8")
        assert version.original_filename == body["original_filename"]
        assert version.content_hash == sha256(raw).hexdigest()
        assert version.size_bytes == len(raw)


@pytest.mark.postgres
def test_explicit_title_and_client_scope_fields_not_trusted(upload_client, upload_context):
    other_org = upload_context.organizations[1]
    response = post(upload_client, title="Explicit display title", organization_id=str(other_org.id), company_name="Do not infer or trust", corp_code="12345678", receipt_no="not-an-analysis", version="99")
    assert response.status_code == 201
    assert response.json()["title"] == "Explicit display title"
    assert response.json()["company_name"] is None
    with upload_context.factory() as session:
        memo = session.get(Memo, UUID(response.json()["id"]))
        assert memo.organization_id == upload_context.users[0].organization_id
        assert memo.current_version == 1


@pytest.mark.postgres
@pytest.mark.parametrize("raw,name,mime,status,code", [
    (b"", "memo.txt", "text/plain", 400, "EMPTY_MEMO"),
    (b" \n\t", "memo.txt", "text/plain", 400, "EMPTY_MEMO"),
    (b"\xef\xbb\xbf", "memo.txt", "text/plain", 400, "EMPTY_MEMO"),
    (b"text", "memo.pdf", "application/pdf", 415, "UNSUPPORTED_MEMO_FORMAT"),
    (b"text", "memo.pdf", "text/plain", 415, "UNSUPPORTED_MEMO_FORMAT"),
    (b"text", "memo.txt", "application/pdf", 415, "UNSUPPORTED_MEMO_FORMAT"),
    (b"text", "memo.md", "text/markdown", 415, "UNSUPPORTED_MEMO_FORMAT"),
    (b"\xff\xfe", "memo.txt", "text/plain", 400, "INVALID_MEMO_ENCODING"),
    (b"text", "memo.txt", "text/plain; charset=latin-1", 400, "INVALID_MEMO_ENCODING"),
    (b"a\x00b", "memo.txt", "text/plain", 400, "INVALID_MEMO_TEXT"),
    (b"x" * 257, "memo.txt", "text/plain", 413, "MEMO_FILE_TOO_LARGE"),
])
def test_invalid_uploads_leave_no_memo(upload_client, upload_context, raw, name, mime, status, code):
    response = post(upload_client, raw, name, mime)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert_empty(upload_context)


@pytest.mark.postgres
def test_exact_byte_limit_bom_and_hash_of_original_bytes(upload_client, upload_context):
    raw = b"\xef\xbb\xbf" + "한글\n".encode("utf-8")
    upload_context.settings.memo_upload_max_bytes = len(raw)
    response = post(upload_client, raw, "bom.TXT", "text/plain; charset=utf-8")
    assert response.status_code == 201
    memo_id = response.json()["id"]
    assert response.json()["size_bytes"] == len(raw)
    assert response.json()["content_hash"] == sha256(raw).hexdigest()
    detail = upload_client.get(f"/api/v1/memos/{memo_id}/versions/1").json()
    assert detail["content"] == "한글\n"


@pytest.mark.postgres
def test_same_file_can_be_uploaded_twice(upload_client):
    first, second = post(upload_client).json(), post(upload_client).json()
    assert first["id"] != second["id"]
    assert first["content_hash"] == second["content_hash"]


@pytest.mark.postgres
def test_upload_read_api_metadata_pagination_and_organization_isolation(upload_client, upload_context):
    ids = [post(upload_client, title=f"Memo {index}").json()["id"] for index in range(3)]
    memo_id = ids[0]
    response = upload_client.get("/api/v1/memos", params={"limit": 1, "offset": 1})
    assert response.status_code == 200 and response.json()[0]["id"] == ids[1]
    detail = upload_client.get(f"/api/v1/memos/{memo_id}")
    assert detail.status_code == 200 and detail.json()["company_name"] is None
    versions = upload_client.get(f"/api/v1/memos/{memo_id}/versions").json()
    assert len(versions) == 1
    assert "content" not in versions[0]
    for field in ("original_filename", "content_type", "size_bytes", "content_hash", "created_by", "created_at"):
        assert versions[0][field] is not None
    detail = upload_client.get(f"/api/v1/memos/{memo_id}/versions/1")
    assert detail.json()["content"] == "Original memo content"
    assert upload_client.get(f"/api/v1/memos/{memo_id}/versions/2").status_code == 404
    assert upload_client.get(f"/api/v1/memos/{uuid4()}").status_code == 404
    user_b = upload_context.users[1]
    upload_client.headers["Authorization"] = "Bearer " + create_access_token(user_b, settings=upload_context.settings)
    assert upload_client.get("/api/v1/memos").json() == []
    for suffix in ("", "/versions", "/versions/1"):
        assert upload_client.get(f"/api/v1/memos/{memo_id}{suffix}").status_code == 404


@pytest.mark.postgres
@pytest.mark.parametrize("failure_point", ["memo", "version", "commit"])
def test_upload_rolls_back_both_rows_and_recovers_session(upload_context, failure_point):
    with upload_context.factory() as session:
        repo = MemoRepository(session)
        service = MemoService(repo, max_upload_bytes=256)
        if failure_point == "commit":
            target, name, replacement = session, "commit", RuntimeError("injected commit failure")
        else:
            target = repo
            name = "add_memo" if failure_point == "memo" else "add_version"
            original = getattr(repo, name)

            def invalid_row(row):
                if failure_point == "memo":
                    row.current_version = 0
                else:
                    row.version = 0
                return original(row)  # real PostgreSQL CHECK violation during flush

            replacement = invalid_row
        with patch.object(target, name, side_effect=replacement):
            with pytest.raises((IntegrityError, RuntimeError)):
                service.create_from_upload(stream=BytesIO(b"memo"), filename="memo.txt", content_type="text/plain", organization_id=upload_context.users[0].organization_id, created_by=upload_context.users[0].id)
        # Checked before closing Session: Service must explicitly rollback flush failure.
        assert not session.in_transaction()
        assert session.scalar(text("SELECT 1")) == 1
        assert_empty(upload_context)


@pytest.mark.postgres
def test_repository_only_flushes_memo_and_version(upload_context):
    user = upload_context.users[0]
    with upload_context.factory() as session:
        repo = MemoRepository(session)
        memo = repo.add_memo(Memo(organization_id=user.organization_id, company_name=None, title="Uncommitted", current_version=1))
        repo.add_version(MemoVersion(memo_id=memo.id, version=1, content="Uncommitted", created_by=user.id))
        assert memo.id is not None
        assert_empty(upload_context)  # observer does not see uncommitted insertion
        session.rollback()
    assert_empty(upload_context)


def test_upload_openapi_accepts_file_title_and_company_identifier():
    schema = app.openapi()
    body = schema["paths"]["/api/v1/memos"]["post"]["requestBody"]["content"]["multipart/form-data"]["schema"]
    body = schema["components"]["schemas"][body["$ref"].split("/")[-1]]
    assert set(body["properties"]) == {"file", "title", "company_id"}
    assert body["required"] == ["file"]
    assert "/api/v1/memos/{memo_id}/versions" not in schema["paths"] or "post" not in schema["paths"]["/api/v1/memos/{memo_id}/versions"]


def test_upload_without_token_is_401():
    with TestClient(app) as client:
        assert post(client).status_code == 401


def test_extractor_reads_only_limit_plus_one_bytes():
    stream = BytesIO(b"x" * 1000)
    with pytest.raises(MemoFileTooLarge):
        PlainTextMemoExtractor().extract(stream, filename="memo.txt", content_type="text/plain", max_bytes=8)
    assert stream.tell() == 9


@pytest.mark.parametrize("filename", ["../../memo.txt", "C:\\fakepath\\memo.txt"])
def test_filename_paths_are_metadata_basename_only(filename):
    result = PlainTextMemoExtractor().extract(BytesIO(b"memo"), filename=filename, content_type="text/plain", max_bytes=10)
    assert result.original_filename == "memo.txt"


@pytest.mark.parametrize("filename", [None, "a\x00.txt", "a" * 256 + ".txt"])
def test_invalid_metadata_names(filename):
    with pytest.raises(InvalidMemoFilename):
        PlainTextMemoExtractor().extract(BytesIO(b"memo"), filename=filename, content_type="text/plain", max_bytes=10)


def test_size_configuration(monkeypatch):
    monkeypatch.delenv("MEMO_UPLOAD_MAX_BYTES", raising=False)
    assert Settings(_env_file=None).memo_upload_max_bytes == 5242880
    monkeypatch.setenv("MEMO_UPLOAD_MAX_BYTES", "64")
    assert Settings(_env_file=None).memo_upload_max_bytes == 64
    with pytest.raises(ValidationError):
        Settings(_env_file=None, memo_upload_max_bytes=0)


@pytest.mark.postgres
@pytest.mark.parametrize("title,status", [("   ", 400), ("x" * 501, 422)])
def test_invalid_title_does_not_create_partial_rows(upload_client, upload_context, title, status):
    response = post(upload_client, title=title)
    assert response.status_code == status
    assert_empty(upload_context)
