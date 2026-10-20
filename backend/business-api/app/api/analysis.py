from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_analysis_service, require_roles
from app.models.enums import UserRole
from app.schemas.analysis import AnalysisAcceptedResponse, AnalysisCreateRequest
from app.schemas.auth import CurrentUser
from app.services.analysis import AnalysisService

router = APIRouter(prefix="/api/v1/analyses", tags=["analyses"])


@router.post("", response_model=AnalysisAcceptedResponse, status_code=202)
def create_analysis(
    request: AnalysisCreateRequest,
    user: Annotated[CurrentUser, Depends(require_roles(UserRole.RA, UserRole.ANALYST))],
    service: Annotated[AnalysisService, Depends(get_analysis_service)],
) -> AnalysisAcceptedResponse:
    return service.create(
        memo_id=request.memo_id, disclosure_receipt_no=request.disclosure_receipt_no,
        organization_id=user.organization_id, requested_by=user.id,
    )
