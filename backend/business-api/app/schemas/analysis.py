from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


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
