from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MemoSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_name: str | None
    title: str
    current_version: int
    created_at: datetime
    updated_at: datetime


class MemoDetailResponse(MemoSummaryResponse):
    pass


class MemoVersionSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    version: int
    original_filename: str | None
    content_type: str | None
    size_bytes: int | None
    content_hash: str | None
    created_by: UUID
    created_at: datetime


class MemoVersionDetailResponse(MemoVersionSummaryResponse):
    memo_id: UUID
    content: str


class MemoUploadResponse(MemoSummaryResponse):
    original_filename: str
    content_type: str
    size_bytes: int
    content_hash: str
