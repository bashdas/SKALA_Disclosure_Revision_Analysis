from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AnalysisStage, AnalysisStatus, PerspectiveType


class AnalysisCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    memo_id: UUID
    # OpenDART receipt identifiers are exactly 14 ASCII digits; no remote lookup here.
    disclosure_receipt_no: str = Field(pattern=r"^[0-9]{14}$", min_length=14, max_length=14)


class AnalysisAcceptedResponse(BaseModel):
    task_id: UUID
    status: Literal["QUEUED"] = "QUEUED"
    created_at: datetime


class AnalysisMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    message_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    type: Literal["RUN_ANALYSIS"] = "RUN_ANALYSIS"
    retry_count: int = Field(default=0, ge=0)


class AnalysisDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    task_id: UUID = Field(validation_alias="id")
    memo_id: UUID
    base_memo_version: int
    disclosure_receipt_no: str
    status: AnalysisStatus
    current_stage: AnalysisStage | None
    has_warnings: bool
    error_stage: AnalysisStage | None
    error_code: str | None
    corp_code: str | None
    company_name_snapshot: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AnalysisEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    sequence: int
    event_type: str
    payload: dict = Field(validation_alias="payload_json")
    created_at: datetime


class AnalysisCancelResponse(BaseModel):
    task_id: UUID
    status: Literal["CANCELLED"] = "CANCELLED"


class AnalysisEventPayload(BaseModel):
    """Explicit summary fields; callers must never put secrets in free text."""
    model_config = ConfigDict(extra="forbid")
    status: AnalysisStatus | None = None
    stage: AnalysisStage | None = None
    code: str | None = Field(default=None, max_length=100, pattern=r"^[A-Z0-9_]+$")
    message: str | None = Field(default=None, max_length=500)
    perspective: PerspectiveType | None = None
    reason: str | None = Field(default=None, max_length=1000)
