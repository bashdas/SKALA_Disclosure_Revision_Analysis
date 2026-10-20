"""Tool 입출력 모델 — docs/05 §1~2 계약의 단일 원천.

LangGraph 담당은 이 모듈로 `structured_content`를 검증합니다 (예: FilingDiff.model_validate(...)).
05 대비 추가 사항: Meta.source에 "mock", 오류 코드 NOT_IMPLEMENTED.
"""

from datetime import UTC, date, datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_serializer

from dart_core.interface import DataSource
from dart_core.models import CorrectionKind, ValueType, ValueUnit

RceptNo = Field(pattern=r"^\d{14}$")
CorpCode = Field(pattern=r"^\d{8}$")
MOCK_WARNING = "MOCK_DATA: 테스트용 가상 데이터입니다. 실제 공시나 메모가 아닙니다."


def dart_url(rcept_no: str) -> str:
    return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── 공통 하위 타입 (05 §1-1) ──────────────────────────────────────────────


class Meta(Model):
    source: DataSource
    generated_at: AwareDatetime
    engine_version: str | None = None
    parser_version: str | None = None
    warnings: list[str]

    @field_serializer("generated_at")
    def _z(self, v: datetime) -> str:
        return v.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    @classmethod
    def build(cls, source: DataSource, warnings: list[str] | None = None, **versions: str | None) -> "Meta":
        w = list(warnings or [])
        if source == "mock":
            w.insert(0, MOCK_WARNING)
        return cls(source=source, generated_at=utc_now(), warnings=w, **versions)


class FilingRef(Model):
    rcept_no: str = RceptNo
    report_nm: str
    rcept_dt: date


class FilingSummary(Model):
    rcept_no: str = RceptNo
    corp_code: str = CorpCode
    corp_name: str
    stock_code: str | None = None
    corp_cls: Literal["Y", "K", "N", "E"] | None = None
    report_nm: str = Field(description="OpenDART 원문 그대로")
    base_report_nm: str = Field(description="대괄호 태그 제거·공백/가운뎃점 정규화")
    correction_tags: list[
        Literal["기재정정", "첨부정정", "첨부추가", "변경등록", "연장결정", "발행조건확정", "정정명령부과", "정정제출요구"]
    ]
    is_correction: bool
    correction_kind: CorrectionKind | None = None
    has_later_correction: bool = Field(description="rm에 '정' 포함")
    is_withdrawn: bool = Field(description="rm에 '철' 포함")
    rcept_dt: date
    flr_nm: str | None = None
    rm: str | None = None
    dart_url: str


class Value(Model):
    raw: str | None = Field(max_length=2000, description="원문 셀/각주 텍스트")
    value: float | int | str | None = Field(description="숫자형은 기준 단위 number, date는 'YYYY-MM-DD', text는 정리된 문자열")
    unit: ValueUnit
    raw_unit: str | None = None
    start: date | None = None
    end: date | None = None


class Evidence(Model):
    rcept_no: str = RceptNo
    role: Literal["correction_table", "correction_footnote", "original_document", "corrected_document"]
    file_name: str | None = None
    section_id: str | None = None
    section_title: str | None = None
    table_id: str | None = None
    row_index: int | None = None
    quote: str = Field(max_length=300)
    dart_url: str


class ErrorBody(Model):
    code: Literal[
        "INVALID_ARGUMENT", "COMPANY_NOT_FOUND", "FILING_NOT_FOUND", "NOT_A_CORRECTION", "DOCUMENT_PARSE_FAILED",
        "MEMO_NOT_FOUND", "VERSION_CONFLICT", "UPSTREAM_RATE_LIMITED", "UPSTREAM_UNAVAILABLE", "UPSTREAM_AUTH",
        "NOT_IMPLEMENTED", "INTERNAL",
    ]
    message: str
    retryable: bool
    details: dict = {}


class ErrorResponse(Model):
    """ToolError 메시지 본문(JSON 문자열)의 구조 (05 §1-2)."""

    error: ErrorBody


# ── search_filings (05 §2-1) ─────────────────────────────────────────────


class CompanyMatch(Model):
    corp_code: str = CorpCode
    corp_name: str
    stock_code: str | None = None
    match_type: Literal["corp_code", "stock_code", "exact", "prefix", "substring"]


class SearchFilingsResult(Model):
    status: Literal["ok", "ambiguous_company"]
    company: CompanyMatch | None
    company_candidates: list[CompanyMatch] = Field(max_length=10)
    filings: list[FilingSummary]
    total_count: int = Field(description="필터 적용 전 OpenDART total_count")
    truncated: bool
    meta: Meta


# ── get_filing_document (05 §2-2) ────────────────────────────────────────


class DocumentFile(Model):
    file_name: str
    doc_title: str | None = None


class OutlineEntry(Model):
    section_id: str
    title: str
    level: int
    char_count: int
    table_ids: list[str]


class FilingDocument(Model):
    rcept_no: str = RceptNo
    filing: FilingSummary | None
    files: list[DocumentFile]
    outline: list[OutlineEntry]
    content: dict | None = Field(description="view=section: {section_id, title, text, tables[]}, view=correction: CorrectionBlock")
    truncated: bool
    meta: Meta


# ── get_filing_diff (05 §2-3) ────────────────────────────────────────────

SignalId = Literal[
    "S1_corp", "S2_title", "S3_order", "S4_first_submit_date", "S5_rm_flag", "S6_target_name",
    "S7_before_value_found", "S8_unique",
]
ReviewReason = Literal[
    "FOOTNOTE_UNRESOLVED", "UNIT_UNKNOWN", "TYPE_MISMATCH", "FREE_TEXT", "MULTI_VALUE_CELL", "MATCH_UNCERTAIN",
    "LARGE_DELTA",
]


class CorrectionRef(FilingRef):
    correction_tags: list[str]
    correction_kind: CorrectionKind


class MatchSignal(Model):
    id: SignalId
    passed: bool | None = Field(description="null = 계산 불가")
    weight: float = 0
    detail: str | None = None


class MatchCandidate(FilingRef):
    score: float


class Match(Model):
    status: Literal["matched", "ambiguous", "not_found", "user_specified"]
    original_rcept_no: str | None
    previous_rcept_no: str | None
    chain: list[FilingRef] = Field(description="오래된 순")
    confidence: float = Field(ge=0, le=1)
    needs_review: bool
    signals: list[MatchSignal]
    candidates: list[MatchCandidate]


class CorrectionHeader(Model):
    target_document_name: str | None = None
    first_submitted_date: date | None = None
    history: list[dict] = []
    # 추가 필드: 거래소 수시공시 머리말 '정정관련 공시서류제출일'(바로 앞 버전의 날짜)과 '※ 관련공시'
    previous_filing_date: date | None = None
    related_disclosures: list[dict] = []


class Delta(Model):
    abs: float | int
    pct: float | None


class Extraction(Model):
    method: Literal["correction_table", "correction_footnote", "structured_compare"]
    rule_ids: list[str]


class Change(Model):
    change_id: str = Field(description="'{correction_rcept_no}:c{행번호}', 재계산해도 동일")
    field_key: str = Field(description="표준 키 또는 'raw:<정규화 라벨>'")
    field_label: str
    section_label: str | None = None
    change_type: Literal["modified", "added", "removed", "text_changed", "reformatted"]
    value_type: ValueType
    before: Value
    after: Value
    delta: Delta | None = None
    reason: str | None = None
    regulator_ordered: bool | None = None
    evidence: list[Evidence] = Field(min_length=1)
    extraction: Extraction
    confidence: float = Field(ge=0, le=1)
    needs_review: bool
    review_reasons: list[ReviewReason]


class DiffSummary(Model):
    total: int
    numeric_changes: int
    needs_review_count: int
    field_keys: list[str]


class FilingDiff(Model):
    diff_id: str = Field(description="'{correction_rcept_no}:{engine_version}'")
    correction: CorrectionRef
    match: Match
    correction_header: CorrectionHeader | None
    changes: list[Change]
    summary: DiffSummary
    needs_review: bool
    meta: Meta


# ── get_analysis_memo (05 §2-4) ──────────────────────────────────────────


class MemoSection(Model):
    section_id: str = Field(description="메모 안에서 고정된 ID (예: 's3'). RAG 청크도 같은 ID 사용")
    heading: str
    text: str
    cited_rcept_nos: list[str] = []


class AnalysisMemo(Model):
    memo_id: str
    corp_code: str = CorpCode
    corp_name: str | None = None
    title: str
    author: str
    version: int = Field(description="save_review_decision의 base_version으로 그대로 사용")
    updated_at: AwareDatetime
    source_rcept_nos: list[str]
    sections: list[MemoSection] | None = Field(default=None, description="include_sections=false이면 null")

    @field_serializer("updated_at")
    def _z(self, v: datetime) -> str:
        return v.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class AnalysisMemoResult(Model):
    memos: list[AnalysisMemo]
    meta: Meta


# ── save_review_decision (05 §2-5) ───────────────────────────────────────


class RevisedSection(Model):
    section_id: str
    new_text: str
    proposed_by: Literal["agent", "human_edited"] | None = None


class ReviewDecisionResult(Model):
    decision_id: str
    decision: Literal["approved", "rejected"]
    memo_id: str
    base_version: int
    new_version: int | None = Field(description="approved면 base_version+1, rejected면 null")
    saved_at: AwareDatetime
    idempotent_replay: bool
