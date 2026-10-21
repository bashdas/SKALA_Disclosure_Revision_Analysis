from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FilingSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    corp_code: str | None = None
    title: str | None = None
    is_correction: bool = False
    is_registered: bool = True
    origin_receipt_no: str | None = None
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


class FilingRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    receipt_no: str = Field(pattern=r"^(?:[0-9]{14}|SEC:[0-9]{1,10}:[0-9]{10}-[0-9]{2}-[0-9]{6})$")


class FavoriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    corp_code: str = Field(pattern=r"^(?:[0-9]{8}|SEC:[0-9]{1,10})$")


class FavoriteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    corp_code: str
    company_name: str
    stock_code: str
