"""파이프라인 산출물 모델 (docs/05 §3). Business MCP는 이 모델에만 의존합니다."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

CorrectionKind = Literal["content", "attachment", "terms_fixed", "other"]
ValueUnit = Literal["KRW", "SHARES", "PERCENT", "KRW_PER_SHARE", "DATE", "NONE"]
ValueType = Literal["amount", "shares", "ratio", "price", "date", "date_range", "number", "text"]


class CompanyHit(BaseModel):
    """resolve_company 결과 1건. (05 §3 시그니처에만 등장해 필드를 여기서 정의)"""

    corp_code: str = Field(pattern=r"^\d{8}$")
    corp_name: str
    stock_code: str | None = None
    match_type: Literal["corp_code", "stock_code", "exact", "prefix", "substring"]


class FilingMeta(BaseModel):
    """list.json 1행 + 계산 필드. FilingSummary와 필드가 같습니다."""

    rcept_no: str = Field(pattern=r"^\d{14}$")
    corp_code: str = Field(pattern=r"^\d{8}$")
    corp_name: str
    stock_code: str | None = None
    corp_cls: Literal["Y", "K", "N", "E"] | None = None
    report_nm: str
    base_report_nm: str
    correction_tags: list[str]
    is_correction: bool
    correction_kind: CorrectionKind | None = None
    has_later_correction: bool
    is_withdrawn: bool
    rcept_dt: date
    flr_nm: str | None = None
    rm: str | None = None
    pblntf_ty: str | None = None


class Cell(BaseModel):
    text: str
    colspan: int = 1
    rowspan: int = 1
    links: list[str] = []  # 셀 안 링크의 접수번호(rcpNo) — '※ 관련공시' 행 추적용 (추가 필드)


class Table(BaseModel):
    table_id: str
    section_id: str
    caption: str | None = None
    unit_hint: str | None = None
    rows: list[list[Cell]]


class Section(BaseModel):
    section_id: str
    file_name: str
    title: str
    level: int
    text: str
    table_ids: list[str]


class CorrectionItem(BaseModel):
    row_index: int  # 정정사항 표에서 머리글 제외 1부터
    item_label: str  # '항목' 열 원문
    regulator_ordered: bool | None = None  # '정정요구ㆍ명령 관련 여부' (열이 없으면 None)
    reason: str | None = None  # '정정사유'
    before_raw: str  # 셀 원문 ('(주1) 정정 전' 같은 참조 포함)
    after_raw: str
    before_footnote: str | None = None  # 해석한 각주 본문 (없으면 None)
    after_footnote: str | None = None
    table_id: str  # 정정사항 표의 table_id
    # 추가 필드: row_index는 정정사항 표가 여러 개여도 문서 안에서 겹치지 않는 순번(change_id용),
    # table_row_index는 그 표 안의 데이터 행 번호(머리글 제외 1부터, evidence.row_index용)
    table_row_index: int | None = None


class CorrectionBlock(BaseModel):
    target_document_name: str | None = None
    first_submitted_date: date | None = None
    history: list[dict] = []  # [{date, document_name, note}]
    items: list[CorrectionItem]
    footnotes: dict[str, dict] = {}  # {"주1": {"before": str|None, "after": str|None}}
    unresolved_refs: list[str] = []  # 해석하지 못한 각주 키
    # ── 추가 필드 (실제 원문 관찰 결과, docs/spike_notes.md) ──
    # 거래소 수시공시 머리말 '정정관련 공시서류제출일': 최초 원본이 아니라 바로 앞 버전(이전 정정일 수 있음)의 날짜.
    # first_submitted_date는 라벨이 '최초제출일'일 때만 채웁니다.
    previous_filing_date: date | None = None
    related_disclosures: list[dict] = []  # '※ 관련공시' 행: [{date, document_name, rcept_no|None}]
    parse_warnings: list[str] = []  # 일부 행·각주를 확정하지 못함 → diff needs_review


class ParsedDocument(BaseModel):
    rcept_no: str = Field(pattern=r"^\d{14}$")
    parser_version: str
    files: list[dict]  # [{file_name, doc_title}]
    sections: list[Section]
    tables: list[Table]
    correction: CorrectionBlock | None = None  # 정정 공시가 아니거나 머리말을 못 찾으면 None
    parse_warnings: list[str] = []  # XML 복구 파싱 등 불완전한 파싱 표시 (추가 필드)


class ParsedValue(BaseModel):
    """parse_value 결과 (05 §3 시그니처에만 등장해 필드를 여기서 정의).

    value_type이 None이면 빈 값(R-NULL-01)입니다.
    """

    raw: str | None
    value: float | int | str | None
    unit: ValueUnit
    raw_unit: str | None = None
    start: date | None = None
    end: date | None = None
    value_type: ValueType | None
    rule_ids: list[str] = []
    unit_unknown: bool = False  # 숫자인데 단위를 판정하지 못함 → UNIT_UNKNOWN
    multi_value: bool = False  # 한 셀에 숫자가 여러 개 → MULTI_VALUE_CELL
