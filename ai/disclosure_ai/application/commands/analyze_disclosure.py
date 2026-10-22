from uuid import UUID

from pydantic import Field

from disclosure_ai.domain.models.base import Model


class AnalysisRequest(Model):
    analysis_task_id: UUID
    memo_id: UUID
    base_memo_version: int = Field(ge=1)
    disclosure_receipt_no: str = Field(
        pattern=r"^(?:[0-9]{14}|SEC:[0-9]{1,10}:[0-9]{10}-[0-9]{2}-[0-9]{6})$"
    )
    company_name_snapshot: str = Field(min_length=1, max_length=255)
    corp_code: str | None = Field(default=None, pattern=r"^[0-9]{8}$")
    thread_id: str = Field(min_length=1, max_length=255)
