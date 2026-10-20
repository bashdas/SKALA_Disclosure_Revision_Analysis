from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.internal.dependencies import get_internal_analysis_service, verify_internal_api_key
from app.schemas.analysis import AnalysisEventResponse
from app.schemas.internal import (
    AnalysisContextResponse, InternalEventRequest, InternalStateRequest, InternalStatusResponse,
    PerspectiveCreateRequest, PerspectiveResponse, PerspectiveUpdateRequest,
    ReportSaveRequest, ReportSavedResponse,
)
from app.services.internal_analysis import InternalAnalysisService

router = APIRouter(prefix="/internal/analyses", tags=["internal"], dependencies=[Depends(verify_internal_api_key)])
Service = Annotated[InternalAnalysisService, Depends(get_internal_analysis_service)]


@router.get("/{task_id}/context", response_model=AnalysisContextResponse)
def get_context(task_id: UUID, service: Service) -> AnalysisContextResponse:
    return service.get_context(task_id)


@router.get("/{task_id}/status", response_model=InternalStatusResponse)
def get_status(task_id: UUID, service: Service) -> InternalStatusResponse:
    return service.get_status(task_id)


@router.post("/{task_id}/events", response_model=AnalysisEventResponse, status_code=201)
def append_event(task_id: UUID, request: InternalEventRequest, service: Service) -> AnalysisEventResponse:
    return service.append_event(task_id, request)


@router.post("/{task_id}/state", response_model=InternalStatusResponse)
def update_state(task_id: UUID, request: InternalStateRequest, service: Service) -> InternalStatusResponse:
    return service.update_state(task_id, request)


@router.post("/{task_id}/perspectives", response_model=PerspectiveResponse)
def register_perspective(task_id: UUID, request: PerspectiveCreateRequest, service: Service) -> PerspectiveResponse:
    return service.register_perspective(task_id, request)


@router.patch("/{task_id}/perspectives/{perspective_id}", response_model=PerspectiveResponse)
def update_perspective(task_id: UUID, perspective_id: UUID, request: PerspectiveUpdateRequest, service: Service) -> PerspectiveResponse:
    return service.update_perspective(task_id, perspective_id, request)


@router.post("/{task_id}/report", response_model=ReportSavedResponse)
def save_report(task_id: UUID, request: ReportSaveRequest, service: Service) -> ReportSavedResponse:
    return service.save_report(task_id, request)
