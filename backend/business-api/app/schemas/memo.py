from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MemoSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_name: str
    title: str
    current_version: int
    created_at: datetime
    updated_at: datetime


class MemoDetailResponse(MemoSummaryResponse):
    pass


class MemoVersionSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    version: int
    created_by: UUID
    created_at: datetime


class MemoVersionDetailResponse(MemoVersionSummaryResponse):
    memo_id: UUID
    content: str
