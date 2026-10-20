from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import create_access_token
from app.domain.resource_exceptions import FilingNotFound, MemoNotFound, MemoVersionNotFound
from app.main import app
from app.models import Filing, FilingVersion, Memo, MemoVersion, Organization, User
from app.models.enums import UserRole
from app.repositories import FilingRepository, MemoRepository
from app.services.filing import FilingService
from app.services.memo import MemoService
from test_auth_security import auth_settings
from test_domain import db, graph, migrated_engine


@pytest.fixture
def records(db, graph):
    early = datetime(2026, 1, 1, tzinfo=timezone.utc)
    later = datetime(2026, 1, 3, tzinfo=timezone.utc)
    graph.filing.filed_at = early
    graph.memo.current_version = 2
    graph.memo.updated_at = early
    org = Organization(name="Foreign organization")
    db.add(org)
    db.flush()
    other_user = User(organization_id=org.id, email="foreign@example.test", password_hash="unused-hash", role=UserRole.RA)
    same_receipt = Filing(organization_id=org.id, company_name="Example", receipt_no=graph.filing.receipt_no, filing_type="contract", filed_at=later)
    only_foreign = Filing(organization_id=org.id, company_name="Example", receipt_no="foreign-only", filing_type="contract", filed_at=later)
    foreign_memo = Memo(organization_id=org.id, company_name="Example", title="Foreign memo")
    own_filings = [graph.filing, *[Filing(organization_id=graph.org.id, company_name=company, receipt_no=str(uuid4()), filing_type=kind, filed_at=later) for company, kind in [("Example", "correction"), ("Other company", "contract")]]]
    own_memos = [graph.memo, *[Memo(organization_id=graph.org.id, company_name=company, title="Own memo", updated_at=later) for company in ("Example", "Other company")]]
    db.add_all([other_user, same_receipt, only_foreign, foreign_memo, *own_filings[1:], *own_memos[1:]])
    db.flush()
    own_version2 = MemoVersion(memo_id=graph.memo.id, version=2, content="Version two", created_by=graph.user.id)
    db.add_all([
        FilingVersion(filing_id=graph.filing.id, version=1, raw_content="Own original filing", content_hash="hash-1"),
        FilingVersion(filing_id=graph.filing.id, version=2, raw_content="Own correction raw content", content_hash="hash-2"),
        FilingVersion(filing_id=same_receipt.id, version=1, raw_content="FOREIGN FILING SECRET", content_hash="foreign-hash"),
        MemoVersion(memo_id=foreign_memo.id, version=1, content="FOREIGN MEMO SECRET", created_by=other_user.id),
        own_version2,
    ])
    db.flush()
    return SimpleNamespace(org=org, same_receipt=same_receipt, only_foreign=only_foreign, memo=foreign_memo, own_filings=own_filings, own_memos=own_memos, own_version2=own_version2)


@pytest.fixture
def read_client(db, graph, records, auth_settings):
    previous = app.dependency_overrides.copy()

    def session_override():
        yield db

    app.dependency_overrides[get_db] = session_override
    app.dependency_overrides[get_settings] = lambda: auth_settings
    headers = {"Authorization": "Bearer " + create_access_token(graph.user, settings=auth_settings)}
    try:
        with TestClient(app, headers=headers) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def urls(graph):
    return [
        "/api/v1/filings", f"/api/v1/filings/{graph.filing.id}",
        f"/api/v1/filings/by-receipt/{graph.filing.receipt_no}",
        f"/api/v1/filings/{graph.filing.id}/versions", f"/api/v1/filings/{graph.filing.id}/versions/1",
        "/api/v1/memos", f"/api/v1/memos/{graph.memo.id}",
        f"/api/v1/memos/{graph.memo.id}/versions", f"/api/v1/memos/{graph.memo.id}/versions/1",
    ]


@pytest.mark.parametrize("path", ["/api/v1/filings", "/api/v1/memos", f"/api/v1/filings/{uuid4()}/versions/1", f"/api/v1/memos/{uuid4()}/versions/1"])
def test_read_requires_auth_before_database(path):
    previous = app.dependency_overrides.copy()

    def forbidden_db():
        raise AssertionError("Missing token must not query database")

    app.dependency_overrides[get_db] = forbidden_db
    try:
        with TestClient(app) as client:
            response = client.get(path)
            assert response.status_code == 401
            assert response.headers["www-authenticate"] == "Bearer"
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@pytest.mark.postgres
@pytest.mark.parametrize("resource", ["filings", "memos"])
def test_lists_are_scoped_paginated_stably_sorted(read_client, records, graph, resource):
    objects = records.own_filings if resource == "filings" else records.own_memos
    column = "filed_at" if resource == "filings" else "updated_at"
    expected = [str(item.id) for item in sorted(objects, key=lambda item: (getattr(item, column), item.id.int), reverse=True)]
    path = f"/api/v1/{resource}"
    response = read_client.get(path, params={"organization_id": str(records.org.id)})
    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == expected
    assert [row["id"] for row in read_client.get(path, params={"limit": 1, "offset": 1}).json()] == expected[1:2]
    assert read_client.get(path, params={"offset": 100}).json() == []
    assert len(read_client.get(path, params={"limit": 100}).json()) == 3
    assert all("organization_id" not in row for row in response.json())


@pytest.mark.postgres
@pytest.mark.parametrize("resource", ["filings", "memos"])
@pytest.mark.parametrize("params", [{"limit": 101}, {"limit": 0}, {"limit": -1}, {"offset": -1}, {"limit": "invalid"}])
def test_pagination_validation(read_client, resource, params):
    assert read_client.get(f"/api/v1/{resource}", params=params).status_code == 422


@pytest.mark.postgres
def test_simple_filters_never_cross_organization(read_client, graph):
    rows = read_client.get("/api/v1/filings", params={"company_name": "Example", "filing_type": "contract"}).json()
    assert [row["id"] for row in rows] == [str(graph.filing.id)]
    rows = read_client.get("/api/v1/memos", params={"company_name": "Example"}).json()
    assert len(rows) == 2
    assert read_client.get("/api/v1/filings", params={"company_name": "missing"}).json() == []
    assert read_client.get("/api/v1/memos", params={"company_name": "missing"}).json() == []


@pytest.mark.postgres
def test_filing_details_and_receipt_are_organization_scoped(read_client, graph, records):
    response = read_client.get(f"/api/v1/filings/{graph.filing.id}")
    assert response.status_code == 200
    expected_keys = {"id", "company_name", "receipt_no", "filing_type", "filed_at", "created_at"}
    assert set(response.json()) == expected_keys
    # Same receipt exists in both tenants; only the authenticated tenant is selected.
    response = read_client.get(f"/api/v1/filings/by-receipt/{graph.filing.receipt_no}", params={"organization_id": str(records.org.id)})
    assert response.status_code == 200
    assert response.json()["id"] == str(graph.filing.id)
    assert "raw_content" not in response.json()
    for receipt in (records.only_foreign.receipt_no, "nonexistent"):
        response = read_client.get(f"/api/v1/filings/by-receipt/{receipt}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "FILING_NOT_FOUND"


@pytest.mark.postgres
@pytest.mark.parametrize("resource", ["filings", "memos"])
def test_foreign_and_missing_ids_have_identical_404(read_client, records, resource):
    key = records.same_receipt.id if resource == "filings" else records.memo.id
    foreign = read_client.get(f"/api/v1/{resource}/{key}")
    missing = read_client.get(f"/api/v1/{resource}/{uuid4()}")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


@pytest.mark.postgres
def test_filing_versions_scope_and_content_policy(read_client, graph, records):
    path = f"/api/v1/filings/{graph.filing.id}/versions"
    response = read_client.get(path)
    assert response.status_code == 200
    assert [row["version"] for row in response.json()] == [1, 2]
    assert all(set(row) == {"id", "version", "content_hash", "created_at"} for row in response.json())
    assert [row["version"] for row in read_client.get(path, params={"limit": 1, "offset": 1}).json()] == [2]
    detail = read_client.get(path + "/2")
    assert detail.status_code == 200
    assert detail.json()["raw_content"] == "Own correction raw content"
    assert detail.json()["filing_id"] == str(graph.filing.id)
    missing = read_client.get(path + "/999")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "FILING_VERSION_NOT_FOUND"
    for suffix in ("", "/1"):
        response = read_client.get(f"/api/v1/filings/{records.same_receipt.id}/versions{suffix}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "FILING_NOT_FOUND"
        assert "FOREIGN" not in response.text


@pytest.mark.postgres
def test_memo_details_and_version_content(read_client, graph, records):
    base = f"/api/v1/memos/{graph.memo.id}"
    response = read_client.get(base)
    assert response.status_code == 200
    assert set(response.json()) == {"id", "company_name", "title", "current_version", "created_at", "updated_at"}
    assert response.json()["current_version"] == 2
    response = read_client.get(base + "/versions")
    assert [row["version"] for row in response.json()] == [1, 2]
    assert all(set(row) == {"version", "created_by", "created_at"} for row in response.json())
    assert [row["version"] for row in read_client.get(base + "/versions", params={"limit": 1, "offset": 1}).json()] == [2]
    detail = read_client.get(base + "/versions/1")
    assert detail.json()["content"] == "original"
    assert detail.json()["memo_id"] == str(graph.memo.id)
    current = read_client.get(base + "/versions/2")
    assert current.json()["content"] == records.own_version2.content
    assert current.json()["created_by"] == str(graph.user.id)
    missing = read_client.get(base + "/versions/999")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "MEMO_VERSION_NOT_FOUND"
    for suffix in ("", "/1"):
        response = read_client.get(f"/api/v1/memos/{records.memo.id}/versions{suffix}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "MEMO_NOT_FOUND"
        assert "FOREIGN" not in response.text


@pytest.mark.postgres
@pytest.mark.parametrize("role", [UserRole.RA, UserRole.ANALYST])
def test_both_roles_can_read_all_endpoints(read_client, db, graph, auth_settings, role):
    graph.user.role = role
    db.flush()
    read_client.headers["Authorization"] = "Bearer " + create_access_token(graph.user, settings=auth_settings)
    for path in urls(graph):
        assert read_client.get(path).status_code == 200, path


@pytest.mark.postgres
@pytest.mark.parametrize("resource", ["filings", "memos"])
@pytest.mark.parametrize("version", [0, -1, 2147483648, "not-an-int"])
def test_invalid_version_parameter(read_client, graph, resource, version):
    parent = graph.filing.id if resource == "filings" else graph.memo.id
    assert read_client.get(f"/api/v1/{resource}/{parent}/versions/{version}").status_code == 422


@pytest.mark.postgres
def test_read_services_do_not_commit_or_mutate(read_client, db, graph):
    def forbidden(*args, **kwargs):
        raise AssertionError("Read API must not control caller transaction")
    with patch.object(db, "commit", forbidden), patch.object(db, "rollback", forbidden), patch.object(db, "close", forbidden):
        for path in urls(graph):
            assert read_client.get(path).status_code == 200
    assert graph.memo.current_version == 2
    assert graph.version.content == "original"


@pytest.mark.postgres
def test_current_version_service_only(db, graph, records):
    service = MemoService(MemoRepository(db))
    assert service.get_current_version(graph.memo.id, graph.org.id) is records.own_version2
    with pytest.raises(MemoNotFound):
        service.get_current_version(records.memo.id, graph.org.id)
    graph.memo.current_version = 999
    db.flush()
    with pytest.raises(MemoVersionNotFound):
        service.get_current_version(graph.memo.id, graph.org.id)
    assert "/api/v1/memos/{memo_id}/current-version" not in app.openapi()["paths"]


@pytest.mark.parametrize("service_type,error", [(FilingService, FilingNotFound), (MemoService, MemoNotFound)])
@pytest.mark.parametrize("operation", ["list", "get"])
def test_parent_scope_checked_before_child_lookup(service_type, error, operation):
    repo = MagicMock()
    repo.get_by_id_and_organization.return_value = None
    service = service_type(repo)
    with pytest.raises(error):
        if operation == "list":
            service.list_versions(uuid4(), uuid4())
        else:
            service.get_version(uuid4(), 1, uuid4())
    repo.list_versions.assert_not_called()
    repo.get_version.assert_not_called()


def test_receipt_service_never_uses_unscoped_lookup():
    repo = MagicMock()
    repo.get_by_receipt_no_and_organization.return_value = None
    org = uuid4()
    with pytest.raises(FilingNotFound):
        FilingService(repo).get_by_receipt_no_and_organization("missing", org)
    repo.get_by_receipt_no_and_organization.assert_called_once_with("missing", org)
    repo.list_by_receipt_no.assert_not_called()
