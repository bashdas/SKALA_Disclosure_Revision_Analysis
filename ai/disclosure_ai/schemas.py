from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Perspective = Literal["INDUSTRY_CONTRACT", "FINANCE", "FX_HEDGE", "MARKET_NEWS"]
Impact = Literal["FACT_UPDATE", "CALCULATION_UPDATE", "INTERPRETATION_REVIEW", "NO_IMPACT", "HOLD"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


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
    disclosure_type: Literal["NEW", "CORRECTION", "UNKNOWN"] = "UNKNOWN"


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
    calculation_basis: str | None = None


class Selection(Model):
    perspective_type: Perspective
    selection_reason: str
    question: str


class OmittedPerspective(Model):
    perspective_type: Perspective
    reason: str


class MemoReview(Model):
    status: Literal["KEEP", "HOLD"]
    reason: str
    evidence: list[Source]


class HistoryRequest(Model):
    reason: str = Field(min_length=1, max_length=400)
    evidence: list[Source] = Field(min_length=1, max_length=3)
    receipt_no: str | None = Field(default=None, pattern=r"^[0-9]{14}$",
        description="이번 본문 또는 제공된 후보에 있는 실제 접수번호만 사용합니다. 날짜만 알면 null이며 뒷자리를 추정하지 않습니다.")


class HistoryAssessment(Model):
    status: Literal["REQUIRED", "NOT_REQUIRED", "ALREADY_AVAILABLE", "UNAVAILABLE"]
    reason: str = Field(min_length=1, max_length=400)
    evidence: list[Source] = Field(default_factory=list, max_length=3)


class HistoryComparison(Model):
    receipt_no: str = Field(pattern=r"^[0-9]{14}$")
    subject: str = Field(min_length=1, max_length=100)
    past_fact: str = Field(min_length=1, max_length=300)
    current_fact: str = Field(min_length=1, max_length=300)
    interpretation: str = Field(min_length=1, max_length=400)
    evidence: list[Source] = Field(min_length=2, max_length=4)


class ReviewPoint(Model):
    view_type: Literal["MEMO_REVIEW", "DISCLOSURE_REVIEW"] = "MEMO_REVIEW"
    perspective_type: Perspective
    title: str = Field(min_length=1, max_length=120)
    memo_view: str | None = Field(default=None, min_length=1, max_length=400)
    condition: str | None = Field(default=None, min_length=1, max_length=400)
    disclosure_fact: str = Field(min_length=1, max_length=400)
    reason: str = Field(min_length=1, max_length=500)
    question: str = Field(min_length=1, max_length=400)
    check_items: list[str] = Field(min_length=1, max_length=3)
    evidence: list[Source] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def validate_view(self):
        if self.view_type == "MEMO_REVIEW" and (
            not self.memo_view or not self.memo_view.strip() or len(self.evidence) < 2
        ):
            raise ValueError("Memo reviews require a memo view and both sources")
        if self.view_type == "DISCLOSURE_REVIEW" and self.memo_view is not None:
            raise ValueError("Disclosure reviews must not invent a memo view")
        return self


class MemoSupplement(Model):
    report_document_id: str = Field(pattern=r"^research:[A-Za-z0-9_-]+$")
    report_location: str = Field(pattern=r"^page:(?:[0-9]+|unknown):lines:[0-9]+-[0-9]+$")
    text: str = Field(
        min_length=1, max_length=1500, description="메모에 새로 추가할 한국어 습니다체 문장입니다."
    )
    reason: str = Field(min_length=1, max_length=1000)
    evidence: list[Source] = Field(min_length=1, max_length=5)


class ReportRevision(Model):
    document_id: str = Field(pattern=r"^research:[A-Za-z0-9_-]+$")
    location: str = Field(pattern=r"^page:(?:[0-9]+|unknown):lines:[0-9]+-[0-9]+$")
    after_text: str | None
    reason: str = Field(min_length=1, max_length=1000)
    evidence: list[Source] = Field(min_length=1, max_length=5)


class ResearchAnalysis(Model):
    memo_supplements: list[MemoSupplement] = Field(max_length=3)
    report_revisions: list[ReportRevision] = Field(max_length=3)
    limitations: list[str]


class BaseAnalysis(Model):
    history_assessment: HistoryAssessment = Field(default_factory=lambda: HistoryAssessment(
        status="NOT_REQUIRED", reason="기존 응답에는 과거 공시 필요성의 별도 판단이 없습니다.", evidence=[]))
    summary: str
    history_request: HistoryRequest | None = None
    history_comparisons: list[HistoryComparison] = Field(default_factory=list, max_length=3)
    review_points: list[ReviewPoint] = Field(default_factory=list, max_length=5)
    proposals: list[Proposal]
    selected: list[Selection]
    not_selected: list[OmittedPerspective] = Field(default_factory=list)
    memo_review: MemoReview | None = None
    no_additional_analysis_reason: str | None
    limitations: list[str]


class Lookup(Model):
    tool: Literal["local_search", "financial", "academic", "disclosure_history", "search_market_news", "read_market_news"]
    query: str = Field(min_length=1, max_length=500)
    receipt_no: str | None = Field(default=None, pattern=r"^[0-9]{14}$",
        description="본문 또는 확인된 후보의 실제 번호입니다. 공시일만 있으면 null을 사용합니다.")
    evidence: list[Source] = Field(default_factory=list, max_length=3)
    article_ids: list[str] = Field(default_factory=list, max_length=3)
    news_as_of: str | None = Field(default=None, max_length=40)
    news_days: int = Field(default=7, ge=1, le=30)
    news_scopes: list[Literal["COMPANY", "INDUSTRY", "MACRO"]] = Field(default_factory=list, max_length=3)
    news_topics: list[str] = Field(default_factory=list, max_length=8)
    bsns_year: int | None = Field(default=None, ge=2015, le=2100)
    reprt_code: Literal["11011", "11012", "11013", "11014"] | None = None
    fs_div: Literal["CFS", "OFS"] | None = None


class NewsPlan(Model):
    article_ids: list[str] = Field(max_length=3)
    search_query: str | None = Field(max_length=500)
    reason: str = Field(max_length=500)


class FinancialQuery(Model):
    corp_code: str = Field(pattern=r"^[0-9]{8}$")
    bsns_year: int = Field(ge=2015, le=2100)
    reprt_code: Literal["11011", "11012", "11013", "11014"]
    fs_div: Literal["CFS", "OFS"]


class PerspectiveAnswer(Model):
    status: Literal["COMPLETED", "INSUFFICIENT_EVIDENCE", "NEEDS_TOOLS"]
    findings: str
    sources: list[Source]
    requests: list[Lookup] = Field(max_length=3)
    limitations: list[str]


class ReportText(Model):
    summary: str
    review_points: str = ""
    history: str = ""
    correction: str
    memo_impact: str
    suggestions: str
    perspectives: str
    future_impacts: str = ""
    limitations: str


class OutputReview(Model):
    evidence_check: str = Field(
        default="",
        max_length=2400,
        description="문장 번호별 근거 일치 여부와 조건부 인과관계, 투자 권유 여부를 짧게 확인한 뒤 허용 목록을 작성합니다.",
    )
    safe_indices: list[int] = Field(max_length=128)


class SavedReport(Model):
    content: str = Field(min_length=1, max_length=100000)
    report_json: dict
    has_warnings: bool
    no_additional_analysis_reason: str | None
    generated_at: str


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
