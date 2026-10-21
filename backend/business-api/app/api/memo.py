from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Path, Query, Response, UploadFile

from app.api.dependencies import get_disclosure_source, get_memo_service, require_roles
from app.domain.disclosure_exceptions import DisclosureError
from app.models.enums import UserRole
from app.schemas.auth import CurrentUser
from app.schemas.memo import (
    MemoCompanyRequest,
    MemoDetailResponse,
    MemoSummaryResponse,
    MemoUploadResponse,
    MemoVersionDetailResponse,
    MemoVersionSummaryResponse,
)
from app.services.disclosure_source import DisclosureSource
from app.services.memo import MemoService

router = APIRouter(prefix="/api/v1/memos", tags=["memos"])
Reader = Annotated[CurrentUser, Depends(require_roles(UserRole.RA, UserRole.ANALYST))]
Service = Annotated[MemoService, Depends(get_memo_service)]
Source = Annotated[DisclosureSource, Depends(get_disclosure_source)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


def company_name(source: DisclosureSource, company_id: str) -> str:
    # 클라이언트가 보낸 기업명 대신 조회한 기업 코드의 이름을 저장합니다.
    result = source.call("opendart_search_companies", {"query": company_id, "limit": 20, "offset": 0})
    company = next((row for row in result.get("items", []) if row.get("corp_code") == company_id), None)
    if company is None:
        raise DisclosureError("COMPANY_NOT_FOUND", "기업을 찾지 못했습니다.", 404)
    return company["company_name"]


@router.get("", response_model=list[MemoSummaryResponse])
def list_memos(user: Reader, service: Service, limit: Limit = 20, offset: Offset = 0, company_name: Annotated[str | None, Query(max_length=255)] = None) -> list[MemoSummaryResponse]:
    return [MemoSummaryResponse.model_validate(item) for item in service.list_memos(user.organization_id, limit=limit, offset=offset, company_name=company_name)]


@router.get("/{memo_id}", response_model=MemoDetailResponse)
def get_memo(memo_id: UUID, user: Reader, service: Service) -> MemoDetailResponse:
    return MemoDetailResponse.model_validate(service.get_memo(memo_id, user.organization_id))


@router.get("/{memo_id}/versions", response_model=list[MemoVersionSummaryResponse])
def list_versions(memo_id: UUID, user: Reader, service: Service, limit: Limit = 20, offset: Offset = 0) -> list[MemoVersionSummaryResponse]:
    return [MemoVersionSummaryResponse.model_validate(item) for item in service.list_versions(memo_id, user.organization_id, limit=limit, offset=offset)]


@router.get("/{memo_id}/versions/{version}", response_model=MemoVersionDetailResponse)
def get_version(memo_id: UUID, version: Annotated[int, Path(ge=1, le=2147483647)], user: Reader, service: Service) -> MemoVersionDetailResponse:
    return MemoVersionDetailResponse.model_validate(service.get_version(memo_id, version, user.organization_id))


@router.post("", response_model=MemoUploadResponse, status_code=201)
def upload_memo(user: Reader, service: Service, source: Source, file: Annotated[UploadFile, File()], title: Annotated[str | None, Form(max_length=500)] = None, company_id: Annotated[str | None, Form(pattern=r"^(?:[0-9]{8}|SEC:[0-9]{1,10})$")] = None) -> MemoUploadResponse:
    return service.create_from_upload(
        stream=file.file, filename=file.filename, content_type=file.content_type,
        organization_id=user.organization_id, created_by=user.id, title=title,
        company_name=company_name(source, company_id) if company_id else None,
    )


@router.patch("/{memo_id}/company", response_model=MemoSummaryResponse)
def assign_company(memo_id: UUID, request: MemoCompanyRequest, user: Reader, service: Service, source: Source) -> MemoSummaryResponse:
    service.get_memo(memo_id, user.organization_id)
    return service.assign_company(memo_id, user.organization_id, company_name(source, request.company_id))


@router.delete("/{memo_id}", status_code=204)
def delete_memo(memo_id: UUID, user: Reader, service: Service) -> Response:
    service.delete(memo_id, user.organization_id)
    return Response(status_code=204)
