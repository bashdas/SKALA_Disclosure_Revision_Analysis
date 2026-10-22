# pytest fixture는 가져온 이름으로 주입되므로 인자 이름을 유지합니다.
# ruff: noqa: F811
from uuid import UUID, uuid4

import pytest
from app.api.dependencies import get_disclosure_source
from app.main import app
from app.models import Memo, MemoVersion
from sqlalchemy import select
from test_memo_upload import (  # noqa: F401
    auth_settings,
    migrated_engine,
    post,
    upload_client,
    upload_context,
)


class Companies:
    def call(self, tool, arguments):
        assert tool == "opendart_search_companies"
        codes = {
            "00126478": "삼성중공업",
            "00398701": "엘앤에프",
            "SEC:1071739": "CENTENE CORP",
        }
        code = arguments["query"]
        return {
            "items": [{"corp_code": code, "company_name": codes[code]}]
            if code in codes
            else []
        }


@pytest.mark.postgres
def test_upload_company_and_reassignment_preserve_versions(
    upload_client, upload_context
):
    app.dependency_overrides[get_disclosure_source] = Companies
    raw = " 원래 메모\n\n본문 보존 ".encode()
    response = post(
        upload_client, raw=raw, company_id="00126478", company_name="다른 기업"
    )
    assert response.status_code == 201
    row = response.json()
    assert row["company_name"] == "삼성중공업"
    memo_id = row["id"]
    before = upload_client.get(f"/api/v1/memos/{memo_id}/versions/1").json()
    response = upload_client.patch(
        f"/api/v1/memos/{memo_id}/company", json={"company_id": "00398701"}
    )
    assert response.status_code == 200
    assert response.json()["company_name"] == "엘앤에프"
    assert response.json()["current_version"] == 1
    assert upload_client.get(f"/api/v1/memos/{memo_id}/versions/1").json() == before
    assert (
        upload_client.get("/api/v1/memos", params={"company_name": "삼성중공업"}).json()
        == []
    )
    assert (
        len(
            upload_client.get(
                "/api/v1/memos", params={"company_name": "엘앤에프"}
            ).json()
        )
        == 1
    )
    with upload_context.factory() as session:
        assert session.get(Memo, UUID(memo_id)).company_name == "엘앤에프"
        versions = list(
            session.scalars(
                select(MemoVersion).where(MemoVersion.memo_id == UUID(memo_id))
            )
        )
        assert len(versions) == 1 and versions[0].content == raw.decode()


@pytest.mark.postgres
def test_unknown_company_rejected_and_sec_supported(upload_client):
    app.dependency_overrides[get_disclosure_source] = Companies
    assert post(upload_client, company_id="bad").status_code == 422
    assert post(upload_client, company_id="99999999").status_code == 404
    assert upload_client.get("/api/v1/memos").json() == []
    response = post(upload_client, company_id="SEC:1071739")
    assert (
        response.status_code == 201
        and response.json()["company_name"] == "CENTENE CORP"
    )


@pytest.mark.postgres
def test_assignment_cannot_change_another_organization(upload_client, upload_context):
    from app.core.security import create_access_token

    app.dependency_overrides[get_disclosure_source] = Companies
    memo_id = post(upload_client).json()["id"]
    upload_client.headers["Authorization"] = "Bearer " + create_access_token(
        upload_context.users[1], settings=upload_context.settings
    )
    assert (
        upload_client.patch(
            f"/api/v1/memos/{memo_id}/company", json={"company_id": "00126478"}
        ).status_code
        == 404
    )
    with upload_context.factory() as session:
        assert session.get(Memo, UUID(memo_id)).company_name is None
    assert (
        upload_client.patch(
            f"/api/v1/memos/{uuid4()}/company", json={"company_id": "00126478"}
        ).status_code
        == 404
    )
