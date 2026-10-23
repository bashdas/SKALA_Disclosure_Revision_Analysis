from datetime import date
from io import BytesIO
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from urllib.parse import quote

from app.api.dependencies import require_roles, get_disclosure_source
from app.api.memo import company_name
from app.api.internal.dependencies import verify_internal_api_key
from app.core.database import get_db
from app.models import InternalReportVersion
from app.models.enums import UserRole
from app.schemas.auth import CurrentUser
from app.schemas.internal_report import ReportMetadata, ReportEdit, ReportSummary, ReportDetail, ReportVersion
from app.services.disclosure_source import DisclosureSource
from app.services.internal_report import InternalReportService, extract_pdf
from fastapi import HTTPException

router = APIRouter(prefix="/api/v1/internal-reports", tags=["internal-reports"])
internal_router = APIRouter(prefix="/internal/analyses", dependencies=[Depends(verify_internal_api_key)])
Reader = Annotated[CurrentUser, Depends(require_roles(UserRole.RA, UserRole.ANALYST))]
Writer = Annotated[CurrentUser, Depends(require_roles(UserRole.ANALYST))]


def get_report_service(session: Annotated[Session, Depends(get_db)]):
    return InternalReportService(session)


Service = Annotated[InternalReportService, Depends(get_report_service)]
Source = Annotated[DisclosureSource, Depends(get_disclosure_source)]


@router.get("", response_model=list[ReportSummary])
def list_reports(user: Reader, service: Service, limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0), corp_code: str | None = Query(None, pattern=r"^[0-9]{8}$")):
    return service.list(user.organization_id, limit, offset, corp_code)


@router.post("", response_model=ReportSummary, status_code=201)
def create_report(user: Writer, service: Service, source: Source,
    file: Annotated[UploadFile, File()], title: Annotated[str, Form(min_length=1, max_length=500)],
    corp_code: Annotated[str, Form(pattern=r"^[0-9]{8}$")], published_at: Annotated[date, Form()]):
    try:
        metadata = ReportMetadata(title=title, corp_code=corp_code, published_at=published_at)
    except ValidationError:
        raise HTTPException(422, "리포트 정보를 확인해 주세요.") from None
    return service.save(user, metadata.model_dump(), company_name(source, corp_code),
        extract_pdf(file.file, file.filename))


@router.get("/{report_id}", response_model=ReportDetail)
def detail(report_id: UUID, user: Reader, service: Service):
    report = service.get(report_id, user.organization_id)
    version = service.version(report)
    return {**ReportSummary.model_validate(report).model_dump(), "content": version.content,
        "original_filename": version.original_filename}


@router.patch("/{report_id}", response_model=ReportSummary)
def edit(report_id: UUID, body: ReportEdit, user: Writer, service: Service, source: Source):
    service.get(report_id, user.organization_id)
    return service.save(user, body.model_dump(exclude={"base_version"}), company_name(source, body.corp_code),
        report_id=report_id, base_version=body.base_version)


@router.post("/{report_id}/versions", response_model=ReportSummary)
def replace_pdf(report_id: UUID, user: Writer, service: Service,
    file: Annotated[UploadFile, File()], base_version: Annotated[int, Form(ge=1)]):
    report = service.get(report_id, user.organization_id)
    metadata = {key: getattr(report, key) for key in ("title", "corp_code", "published_at")}
    return service.save(user, metadata, report.company_name, extract_pdf(file.file, file.filename),
        report_id=report_id, base_version=base_version)


@router.get("/{report_id}/versions", response_model=list[ReportVersion])
def versions(report_id: UUID, user: Reader, service: Service,
    limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    service.get(report_id, user.organization_id)
    return service.session.scalars(select(InternalReportVersion).where(InternalReportVersion.report_id == report_id)
        .order_by(InternalReportVersion.version.desc()).limit(limit).offset(offset)).all()


@router.get("/{report_id}/file")
def download(report_id: UUID, user: Reader, service: Service, version: int | None = Query(None, ge=1)):
    report = service.get(report_id, user.organization_id)
    row = service.version(report, version)
    return StreamingResponse(BytesIO(row.pdf_data), media_type="application/pdf", headers={
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(row.original_filename),
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.delete("/{report_id}", status_code=204)
def delete(report_id: UUID, user: Writer, service: Service):
    service.delete(report_id, user.organization_id)


@internal_router.get("/{task_id}/research-reports")
def analysis_reports(task_id: UUID, service: Service):
    return service.for_analysis(task_id)
