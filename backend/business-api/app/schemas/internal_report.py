from datetime import date, datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReportMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=500)
    corp_code: str = Field(pattern=r"^[0-9]{8}$")
    published_at: date

    @field_validator("title")
    @classmethod
    def valid_title(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 32 for c in value):
            raise ValueError("제목을 확인해 주세요.")
        return value


class ReportEdit(ReportMetadata):
    base_version: int = Field(ge=1)


class ReportSummary(ReportMetadata):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_name: str
    current_version: int
    created_at: datetime
    updated_at: datetime


class ReportVersion(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    version: int
    title: str
    corp_code: str
    company_name: str
    published_at: date
    original_filename: str
    content_hash: str
    created_at: datetime


class ReportDetail(ReportSummary):
    content: str
    original_filename: str
