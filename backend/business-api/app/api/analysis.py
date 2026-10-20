from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse

from app.api.dependencies import (
    get_analysis_service, get_analysis_stream, get_stream_current_user, require_roles,
)
from app.domain.analysis_exceptions import InvalidStreamQuery
from app.models.enums import UserRole
from app.schemas.analysis import (
    AnalysisAcceptedResponse, AnalysisCreateRequest, AnalysisDetailResponse,
    AnalysisCancelResponse, AnalysisEventResponse,
)
from app.schemas.auth import CurrentUser
from app.services.analysis import AnalysisService
from app.services.analysis_stream import AnalysisEventStream, MAX_SEQUENCE, resolve_after_sequence

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


Reader = Annotated[CurrentUser, Depends(require_roles(UserRole.RA, UserRole.ANALYST))]
Service = Annotated[AnalysisService, Depends(get_analysis_service)]
Cursor = Annotated[int, Query(ge=0, le=MAX_SEQUENCE)]


@router.get("/{task_id}", response_model=AnalysisDetailResponse)
def get_analysis(task_id: UUID, user: Reader, service: Service) -> AnalysisDetailResponse:
    return service.get_analysis(task_id, user.organization_id)


@router.get("/{task_id}/events", response_model=list[AnalysisEventResponse])
def list_events(task_id: UUID, user: Reader, service: Service, after_sequence: Cursor = 0,
                limit: Annotated[int, Query(ge=1, le=500)] = 200) -> list[AnalysisEventResponse]:
    return service.list_events(task_id, user.organization_id, after_sequence=after_sequence, limit=limit)


@router.get("/{task_id}/events/stream", response_class=StreamingResponse)
def stream_events(
    task_id: UUID, request: Request,
    user: Annotated[CurrentUser, Depends(require_roles(UserRole.RA, UserRole.ANALYST, user_dependency=get_stream_current_user))],
    stream: Annotated[AnalysisEventStream, Depends(get_analysis_stream)],
    after_sequence: Annotated[int | None, Query(ge=0, le=MAX_SEQUENCE)] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    if set(request.query_params) - {"after_sequence"}:
        raise InvalidStreamQuery()
    cursor = resolve_after_sequence(after_sequence, last_event_id)
    # Resolve scope before sending 200 headers. This Session is already closed on return.
    initial = stream.snapshot(task_id, user.organization_id, cursor)
    return StreamingResponse(stream.stream(request, task_id, user.organization_id, cursor, initial),
        media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"})


@router.post("/{task_id}/cancel", response_model=AnalysisCancelResponse)
def cancel_analysis(task_id: UUID, user: Reader, service: Service) -> AnalysisCancelResponse:
    return service.cancel_analysis(task_id, user.organization_id, user.id)
