from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Response

from app.api.dependencies import get_filing_service, require_roles
from app.models.enums import UserRole
from app.schemas.auth import CurrentUser
from app.schemas.filing import (
    FilingDetailResponse, FilingSummaryResponse, FilingRegisterRequest,
    FilingVersionDetailResponse, FilingVersionSummaryResponse,
)
from app.services.filing import FilingService

router = APIRouter(prefix="/api/v1/filings", tags=["filings"])
Reader = Annotated[CurrentUser, Depends(require_roles(UserRole.RA, UserRole.ANALYST))]
Service = Annotated[FilingService, Depends(get_filing_service)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.get("", response_model=list[FilingSummaryResponse])
def list_filings(user: Reader, service: Service, limit: Limit = 20, offset: Offset = 0, company_name: Annotated[str | None, Query(max_length=255)] = None, filing_type: Annotated[str | None, Query(max_length=100)] = None) -> list[FilingSummaryResponse]:
    results = service.list_filings(user.organization_id, limit=limit, offset=offset, company_name=company_name, filing_type=filing_type)
    return [FilingSummaryResponse.model_validate(item) for item in results]


@router.get("/by-receipt/{receipt_no}", response_model=FilingDetailResponse)
def get_by_receipt(receipt_no: Annotated[str, Path(min_length=1, max_length=64)], user: Reader, service: Service) -> FilingDetailResponse:
    return FilingDetailResponse.model_validate(service.get_by_receipt_no_and_organization(receipt_no, user.organization_id))


@router.get("/{filing_id}", response_model=FilingDetailResponse)
def get_filing(filing_id: UUID, user: Reader, service: Service) -> FilingDetailResponse:
    return FilingDetailResponse.model_validate(service.get_filing(filing_id, user.organization_id))


@router.get("/{filing_id}/versions", response_model=list[FilingVersionSummaryResponse])
def list_versions(filing_id: UUID, user: Reader, service: Service, limit: Limit = 20, offset: Offset = 0) -> list[FilingVersionSummaryResponse]:
    return [FilingVersionSummaryResponse.model_validate(item) for item in service.list_versions(filing_id, user.organization_id, limit=limit, offset=offset)]


@router.get("/{filing_id}/versions/{version}", response_model=FilingVersionDetailResponse)
def get_version(filing_id: UUID, version: Annotated[int, Path(ge=1, le=2147483647)], user: Reader, service: Service) -> FilingVersionDetailResponse:
    return FilingVersionDetailResponse.model_validate(service.get_version(filing_id, version, user.organization_id))


@router.post("", response_model=FilingDetailResponse)
def register_filing(request: FilingRegisterRequest, user: Reader, service: Service) -> FilingDetailResponse:
    return FilingDetailResponse.model_validate(service.register(request.receipt_no, user.organization_id))


@router.delete("/{filing_id}", status_code=204)
def unregister_filing(filing_id: UUID, user: Reader, service: Service) -> Response:
    service.unregister(filing_id, user.organization_id)
    return Response(status_code=204)


@router.post("/{filing_id}/corrections/check", response_model=list[FilingSummaryResponse])
def check_corrections(filing_id: UUID, user: Reader, service: Service) -> list[FilingSummaryResponse]:
    return [FilingSummaryResponse.model_validate(row) for row in service.check_corrections(filing_id, user.organization_id)]
