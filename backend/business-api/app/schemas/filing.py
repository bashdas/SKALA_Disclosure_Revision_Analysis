from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FilingSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_name: str
    receipt_no: str
    filing_type: str
    filed_at: datetime
    created_at: datetime


class FilingDetailResponse(FilingSummaryResponse):
    pass


class FilingVersionSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    version: int
    content_hash: str
    created_at: datetime


class FilingVersionDetailResponse(FilingVersionSummaryResponse):
    filing_id: UUID
    raw_content: str
