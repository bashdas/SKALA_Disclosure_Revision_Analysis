"""결정적 규칙 단위 테스트: titles(07 §5-1), normalize(05 §7), matching(07 §5-3 필수 6케이스), diff."""

import copy
from datetime import date

import pytest

from business_mcp.errors import InvalidArgument, NotACorrection
from business_mcp.mock import DATA_DIR, MockDartCore, _load
from business_mcp.services.diff import get_filing_diff
from business_mcp.services.field_dictionary import lookup
from dart_core.normalize import parse_value
from dart_core.titles import split_tags, to_filing_meta

BASE = {
    "companies": _load(DATA_DIR / "companies.json"),
    "filings": _load(DATA_DIR / "filings.json"),
    "documents": {p.stem: _load(p) for p in (DATA_DIR / "documents").glob("*.json")},
}


def make_dart(edit=None) -> MockDartCore:
    data = copy.deepcopy(BASE)
    if edit:
        edit(data)
    return MockDartCore(data["companies"], data["filings"], data["documents"])


def filing_row(data, rcept_no) -> dict:
    return next(f for f in data["filings"] if f["rcept_no"] == rcept_no)


# ── titles ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("report_nm, tags, base, is_correction, kind", [
    ("[기재정정]단일판매ㆍ공급계약체결", ["기재정정"], "단일판매ㆍ공급계약체결", True, "content"),
    ("[기재정정][첨부추가]주요사항보고서(유상증자결정)", ["기재정정", "첨부추가"], "주요사항보고서(유상증자결정)", True, "content"),
    ("[발행조건확정]증권신고서(채무증권)", ["발행조건확정"], "증권신고서(채무증권)", True, "terms_fixed"),
    ("단일판매·공급계약체결", [], "단일판매ㆍ공급계약체결", False, None),
    ("[정정명령부과]증권신고서(지분증권)", ["정정명령부과"], "증권신고서(지분증권)", False, None),
    ("  주요사항보고서 (전환사채권발행결정) ", [], "주요사항보고서 (전환사채권발행결정)", False, None),
])
def test_titles(report_nm, tags, base, is_correction, kind):
    assert split_tags(report_nm) == (tags, base)
    meta = to_filing_meta({"rcept_no": "20260101000001", "corp_code": "00000001", "corp_name": "x",
                           "report_nm": report_nm, "rcept_dt": "20260101", "rm": "코정철"})
    assert (meta.is_correction, meta.correction_kind) == (is_correction, kind)
    assert meta.has_later_correction and meta.is_withdrawn


# ── normalize (05 §7 규칙 ID별) ───────────────────────────────────────────


@pytest.mark.parametrize("raw, hint, label, value, unit, rule", [
    ("12,000,000,000", None, None, 12_000_000_000, "NONE", None),  # 단위 없음 → UNIT_UNKNOWN
    ("12,000,000,000원", None, None, 12_000_000_000, "KRW", "R-AMT-01"),
    ("400,000", "백만원", None, 400_000_000_000, "KRW", "R-AMT-02"),
    ("4,000억원", None, None, 400_000_000_000, "KRW", "R-AMT-03"),
    ("1.2조원", None, None, 1_200_000_000_000, "KRW", "R-AMT-03"),
    ("7,000,000주", None, None, 7_000_000, "SHARES", "R-SHR-01"),
    ("15.3%", None, None, 15.3, "PERCENT", "R-PCT-01"),
    ("15.3", "백만원", "최근 매출액 대비", 15.3, "PERCENT", "R-PCT-01"),  # 라벨이 표 단위보다 우선
    ("12,500", "백만원", "전환가액", 12_500, "KRW_PER_SHARE", "R-PRC-01"),
    ("12,500원/주", None, None, 12_500, "KRW_PER_SHARE", "R-PRC-01"),
    ("3,000원", "백만원", None, 3_000, "KRW", "R-UNIT-CELL"),  # 셀 단위 우선
    ("(1,000)", "원", None, -1_000, "KRW", "R-AMT-01"),
    ("△1,000원", None, None, -1_000, "KRW", "R-AMT-01"),
])
def test_parse_numbers(raw, hint, label, value, unit, rule):
    v = parse_value(raw, hint, label=label)
    assert (v.value, v.unit) == (value, unit)
    if rule:
        assert rule in v.rule_ids
    else:
        assert v.unit_unknown and v.value_type == "number"


@pytest.mark.parametrize("raw", ["2026-03-05", "2026.03.05", "2026년 03월 05일", "2026/3/5"])
def test_parse_date(raw):
    v = parse_value(raw)
    assert (v.value, v.unit, v.value_type, v.rule_ids) == ("2026-03-05", "DATE", "date", ["R-DATE-01"])


@pytest.mark.parametrize("raw", ["2026-03-05 ~ 2026-12-31", "2026년 3월 5일부터 2026년 12월 31일까지"])
def test_parse_date_range(raw):
    v = parse_value(raw)
    assert (v.value_type, v.start, v.end) == ("date_range", date(2026, 3, 5), date(2026, 12, 31))


@pytest.mark.parametrize("raw", ["-", "–", "", None, "해당사항 없음", "해당없음"])
def test_parse_null(raw):
    v = parse_value(raw)
    assert v.value is None and v.value_type is None and v.rule_ids == ["R-NULL-01"] and v.raw == raw


def test_parse_text_and_multi_value():
    assert parse_value("가상제약 주식회사").value_type == "text"
    v = parse_value("1차 3,000원, 2차 4,000원")
    assert v.value_type == "text" and v.multi_value


def test_field_dictionary():
    assert lookup("계약금액(원)") == "contract_amount"
    assert lookup("권면(전자등록)총액") == "offering_amount"
    assert lookup("계약기간 - 시작일") == "contract_start_date"  # 뒤쪽(구체적) 라벨 우선
    assert lookup("기타 투자판단에 참고할 사항") is None


# ── matching (07 §5-3 필수 케이스) ────────────────────────────────────────


async def test_match_simple_original():  # (1)
    diff = await get_filing_diff(make_dart(), "20260312000123")
    assert diff.match.status == "matched" and diff.match.confidence >= 0.8 and not diff.match.needs_review


async def test_match_without_header():  # (2) 머리말 없음 → matched + needs_review
    def edit(d):
        d["documents"]["20260312000123"]["correction"] = None
    diff = await get_filing_diff(make_dart(edit), "20260312000123")
    assert diff.match.status == "matched" and diff.match.original_rcept_no == "20260305000045"
    assert diff.match.confidence == 0.25 and diff.match.needs_review
    assert diff.changes == [] and diff.needs_review and diff.correction_header is None


async def test_match_same_day_ambiguous():  # (3)
    diff = await get_filing_diff(make_dart(), "20260617000088")
    assert diff.match.status == "ambiguous" and len(diff.match.candidates) == 2


async def test_match_s7_narrows_same_day_candidates():  # S7: 정정 전 값이 한 후보에만 있음
    def edit(d):
        doc = d["documents"]["20260610000102"]
        for s in doc["sections"]:
            s["text"] = s["text"].replace("5,000,000,000", "3,000,000,000")
        for t in doc["tables"]:
            for row in t["rows"]:
                for cell in row:
                    cell["text"] = cell["text"].replace("5,000,000,000", "3,000,000,000")
    diff = await get_filing_diff(make_dart(edit), "20260617000088")
    s7 = next(s for s in diff.match.signals if s.id == "S7_before_value_found")
    assert diff.match.status == "matched" and diff.match.original_rcept_no == "20260610000101" and s7.passed


async def test_match_second_correction():  # (4)
    m = (await get_filing_diff(make_dart(), "20260415000301")).match
    assert (m.original_rcept_no, m.previous_rcept_no, len(m.chain)) == ("20260401000210", "20260408000155", 3)


async def test_match_original_withdrawn():  # (5)
    def edit(d):
        filing_row(d, "20260305000045")["rm"] = "코철"
    diff = await get_filing_diff(make_dart(edit), "20260312000123")
    assert diff.match.status == "not_found" and diff.match.needs_review
    assert all("MATCH_UNCERTAIN" in c.review_reasons for c in diff.changes)


async def test_non_correction_raises():  # (6)
    with pytest.raises(NotACorrection):
        await get_filing_diff(make_dart(), "20260305000045")


async def test_user_specified_other_company_rejected():
    with pytest.raises(InvalidArgument) as e:
        await get_filing_diff(make_dart(), "20260312000123", original_rcept_no="20260401000210")
    assert e.value.details["failed_signals"] == ["S1_corp", "S2_title", "S3_order"]


async def test_attachment_correction_without_changes():
    def edit(d):
        d["filings"].append({**filing_row(d, "20260312000123"), "rcept_no": "20260320000999", "rcept_dt": "20260320",
                             "report_nm": "[첨부정정]단일판매ㆍ공급계약체결"})
        d["documents"]["20260320000999"] = {**d["documents"]["20260312000123"], "rcept_no": "20260320000999",
                                            "correction": None}
    diff = await get_filing_diff(make_dart(edit), "20260320000999")
    assert diff.correction.correction_kind == "attachment" and diff.changes == []
    assert "첨부 정정: 본문 변경 없음" in diff.meta.warnings


async def test_diff_is_deterministic():
    a = await get_filing_diff(make_dart(), "20260415000301")
    b = await get_filing_diff(make_dart(), "20260415000301")
    dump = lambda d: d.model_dump(exclude={"meta": {"generated_at"}})
    assert dump(a) == dump(b)


# ── 실제 원문에서 발견한 형식 (2026-10-20) ────────────────────────────────


def test_inline_sub_items_without_line_breaks():
    from business_mcp.services.diff import _split_inline_items
    assert _split_inline_items("-주식 수 : 3,385,240-주식 총수 대비 비율(%): 11.18") == \
        "-주식 수 : 3,385,240\n-주식 총수 대비 비율(%): 11.18"
    assert _split_inline_items("- 참석 (명) : 2- 불참 (명) : 1") == "- 참석 (명) : 2\n- 불참 (명) : 1"
    assert _split_inline_items("-전환가액: 2,954") == "-전환가액: 2,954"  # 하나면 그대로
    assert _split_inline_items("-1,000") == "-1,000"  # 음수
    assert _split_inline_items("-기간: 2026-10-27-2027-01-01") == "-기간: 2026-10-27-2027-01-01"  # '-' 뒤 숫자


def test_weak_year_token_does_not_verify_other_event():
    from business_mcp.services.matching import _before_hits
    from dart_core.models import CorrectionBlock, CorrectionItem, ParsedDocument, Section

    def doc(text):
        return ParsedDocument(rcept_no="1" * 14, parser_version="x", files=[], tables=[], sections=[
            Section(section_id="f0.s0", file_name="a", title="t", level=1, text=text, table_ids=[])])

    block = CorrectionBlock(items=[CorrectionItem(
        row_index=1, item_label="9. 기타", table_id="f0.t0", after_raw="-",
        before_raw="※현재 계약금액 및 기간변경과 관련하여 협의중입니다. 상기 매출액은 '2023년도 기준")])
    assert _before_hits(doc("정정관련 공시서류제출일 2023-06-30 다른 계약"), block) == (0, 1)  # 연도만 겹침
    assert _before_hits(doc("본문 ※현재 계약금액 및 기간변경과 관련하여 협의중입니다. 상기 매출액은 '2023년도 기준"),
                        block) == (1, 1)
