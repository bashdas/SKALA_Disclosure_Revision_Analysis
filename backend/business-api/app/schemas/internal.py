"""Task-bound internal contracts. Caller cannot override task identity/scope."""
from datetime import datetime
import json
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from app.domain.analysis_events import AnalysisEventType
from app.models.enums import AnalysisStatus, AnalysisStage, PerspectiveType, PerspectiveStatus
from app.schemas.analysis import AnalysisEventPayload


class InternalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def valid_text(cls, value):
        if isinstance(value, str):
            if "\x00" in value:
                raise ValueError("NUL is not accepted in text")
            try:
                value.encode("utf-8")
            except UnicodeError:
                raise ValueError("Text must be valid UTF-8") from None
        return value


class ContextMemo(BaseModel):
    id: UUID
    version: int
    title: str
    content: str
    content_hash: str | None
    original_filename: str | None


class AnalysisContextResponse(BaseModel):
    task_id: UUID
    organization_id: UUID
    requested_by: UUID
    status: AnalysisStatus
    current_stage: AnalysisStage | None
    memo: ContextMemo
    disclosure_receipt_no: str
    corp_code: str | None
    company_name: str | None
    created_at: datetime
    filing_type: str | None = None
    is_correction: bool | None = None
    filing_title: str | None = None


class InternalStatusResponse(BaseModel):
    task_id: UUID
    status: AnalysisStatus
    current_stage: AnalysisStage | None
    cancelled: bool
    has_warnings: bool


class InternalEventRequest(InternalRequest):
    event_type: AnalysisEventType
    payload: AnalysisEventPayload = Field(default_factory=AnalysisEventPayload)


class InternalStateRequest(InternalRequest):
    status: AnalysisStatus | None = None
    stage: AnalysisStage | None = None
    has_warnings: bool | None = None
    error_stage: AnalysisStage | None = None
    error_code: str | None = Field(default=None, max_length=100, pattern=r"^[A-Z0-9_]+$")
    error_message: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_update(self):
        if self.status is None and self.stage is None and self.has_warnings is None:
            raise ValueError("At least one state field is required")
        if any(value is not None for value in (self.error_stage, self.error_code, self.error_message)) and self.status not in (AnalysisStatus.FAILED, AnalysisStatus.SAVE_FAILED):
            raise ValueError("Error fields require FAILED or SAVE_FAILED status")
        return self


def validate_result(value: dict[str, JsonValue] | None):
    if value is None:
        return value
    sensitive = {"password", "passwordhash", "apikey", "authorization", "accesstoken", "refreshtoken",
                 "internalapikey", "rabbitmqurl", "databaseurl", "secret", "jwt", "jwtsecretkey"}

    def check(item):
        if isinstance(item, str) and "\x00" in item:
            raise ValueError("NUL is not accepted in JSON")
        if isinstance(item, dict):
            for key, child in item.items():
                check(key)
                if key.lower().replace("_", "").replace("-", "") in sensitive:
                    raise ValueError("Sensitive fields are not accepted")
                check(child)
        elif isinstance(item, list):
            for child in item:
                check(child)

    check(value)
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except ValueError:
        raise ValueError("Result must be finite JSON") from None
    if len(encoded) > 1024 * 1024:
        raise ValueError("Result JSON exceeds 1 MiB")
    return value


class PerspectiveCreateRequest(InternalRequest):
    perspective_type: PerspectiveType
    selection_reason: str = Field(min_length=1, max_length=2000)
    question: str = Field(min_length=1, max_length=4000)
    max_tool_calls: int = Field(ge=0, le=1000)
    timeout_seconds: int = Field(gt=0, le=86400)

    @field_validator("selection_reason", "question")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Summary must not be blank")
        return value


class PerspectiveUpdateRequest(InternalRequest):
    status: PerspectiveStatus
    result: dict[str, JsonValue] | None = None
    failure_code: str | None = Field(default=None, max_length=100, pattern=r"^[A-Z0-9_]+$")
    failure_message: str | None = Field(default=None, max_length=500)

    _validate_result = field_validator("result")(validate_result)

    @model_validator(mode="after")
    def validate_terminal_fields(self):
        if self.result is not None and self.status in (PerspectiveStatus.REGISTERED, PerspectiveStatus.RUNNING):
            raise ValueError("Result requires a terminal perspective status")
        if (self.failure_code is not None or self.failure_message is not None) and self.status not in (PerspectiveStatus.FAILED, PerspectiveStatus.INSUFFICIENT_EVIDENCE, PerspectiveStatus.LIMIT_REACHED):
            raise ValueError("Failure details require a degraded perspective status")
        return self


class PerspectiveResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    perspective_id: UUID = Field(validation_alias="id")
    perspective_type: PerspectiveType
    status: PerspectiveStatus


class ReportSaveRequest(InternalRequest):
    content: str = Field(min_length=1, max_length=1024 * 1024)
    report: dict[str, JsonValue]
    has_warnings: bool = False
    no_additional_analysis_reason: str | None = Field(default=None, max_length=2000)

    _validate_result = field_validator("report")(validate_result)

    @field_validator("content")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Report content must not be blank")
        return value


class ReportSavedResponse(BaseModel):
    report_id: UUID
    task_id: UUID
    status: AnalysisStatus
    has_warnings: bool
    generated_at: datetime
    saved_at: datetime | None
