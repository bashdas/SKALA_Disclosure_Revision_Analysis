from typing import Literal

from pydantic import Field

from disclosure_ai.domain.enums import Impact, Perspective
from disclosure_ai.domain.models.base import Model


class Source(Model):
    document_id: str
    location: str
    quote: str
    url: str | None = None
    published_at: str | None = None


class Proposal(Model):
    claim_id: str
    impact_type: Impact
    before_text: str
    after_text: str | None
    reason: str
    evidence: list[Source]


class Selection(Model):
    perspective_type: Perspective
    selection_reason: str
    question: str


class BaseAnalysis(Model):
    summary: str
    proposals: list[Proposal]
    selected: list[Selection]
    no_additional_analysis_reason: str | None
    limitations: list[str]


class Lookup(Model):
    tool: Literal["local_search", "financial", "academic"]
    query: str = Field(min_length=1, max_length=500)
    bsns_year: int | None = Field(default=None, ge=2015, le=2100)
    reprt_code: Literal["11011", "11012", "11013", "11014"] | None = None
    fs_div: Literal["CFS", "OFS"] | None = None


class PerspectiveAnswer(Model):
    status: Literal["COMPLETED", "INSUFFICIENT_EVIDENCE", "NEEDS_TOOLS"]
    findings: str
    sources: list[Source]
    requests: list[Lookup] = Field(max_length=3)
    limitations: list[str]


class OutputReview(Model):
    evidence_check: str = Field(
        default="",
        max_length=2400,
        description="문장 번호별 근거 일치 여부와 조건부 인과관계, 투자 권유 여부를 짧게 확인한 뒤 허용 목록을 작성합니다.",
    )
    safe_indices: list[int] = Field(max_length=128)


class CitedSummary(Model):
    text: str = Field(min_length=1, max_length=500)
    evidence_ids: list[str] = Field(min_length=1, max_length=5)


class FutureImpact(Model):
    condition: str = Field(min_length=1, max_length=250)
    effect: str = Field(min_length=1, max_length=350)
    evidence_ids: list[str] = Field(min_length=1, max_length=5)


class ReportSummary(Model):
    summary: list[CitedSummary] = Field(max_length=3)
    future_impacts: list[FutureImpact] = Field(default_factory=list, max_length=3)
