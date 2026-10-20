"""FastMCP in-memory Client로 Tool 5개의 계약(입출력 스키마, 정상·오류 응답)을 검증합니다 (docs/06 §7)."""

import pytest
from fastmcp import Client

from business_mcp import providers
from business_mcp.schemas import (
    MOCK_WARNING,
    AnalysisMemoResult,
    ErrorResponse,
    FilingDiff,
    SearchFilingsResult,
)
from business_mcp.server import mcp

TOOLS = {"search_filings", "get_filing_document", "get_filing_diff", "get_analysis_memo", "save_review_decision"}

# 05 문서 출력 스키마의 required 목록
REQUIRED_05 = {
    "search_filings": {"status", "company", "company_candidates", "filings", "total_count", "truncated", "meta"},
    "get_filing_document": {"rcept_no", "filing", "files", "outline", "content", "truncated", "meta"},
    "get_filing_diff": {"diff_id", "correction", "match", "correction_header", "changes", "summary", "needs_review",
                        "meta"},
    "get_analysis_memo": {"memos", "meta"},
    "save_review_decision": {"decision_id", "decision", "memo_id", "base_version", "new_version", "saved_at",
                             "idempotent_replay"},
}
REQUIRED_05_DEFS = {
    "FilingSummary": {"rcept_no", "corp_code", "corp_name", "report_nm", "base_report_nm", "correction_tags",
                      "is_correction", "has_later_correction", "is_withdrawn", "rcept_dt", "dart_url"},
    "Value": {"raw", "value", "unit"},
    "Evidence": {"rcept_no", "role", "quote", "dart_url"},
    "Meta": {"source", "generated_at", "warnings"},
    "Match": {"status", "original_rcept_no", "previous_rcept_no", "chain", "confidence", "needs_review", "signals",
              "candidates"},
    "Change": {"change_id", "field_key", "field_label", "change_type", "value_type", "before", "after", "evidence",
               "extraction", "confidence", "needs_review", "review_reasons"},
    "AnalysisMemo": {"memo_id", "corp_code", "title", "author", "version", "updated_at", "source_rcept_nos"},
}


@pytest.fixture
async def client():
    async with Client(mcp) as c:
        yield c


async def call_ok(client, name, args):
    r = await client.call_tool(name, args, raise_on_error=False)
    assert not r.is_error, r.content[0].text
    return r.structured_content


async def call_err(client, name, args) -> ErrorResponse:
    r = await client.call_tool(name, args, raise_on_error=False)
    assert r.is_error
    return ErrorResponse.model_validate_json(r.content[0].text)


# ── Tool 목록과 스키마 ────────────────────────────────────────────────────


async def test_list_tools_and_schemas(client):
    tools = {t.name: t for t in await client.list_tools()}
    assert set(tools) == TOOLS
    for name, t in tools.items():
        assert REQUIRED_05[name] <= set(t.output_schema["required"]), name
        assert t.input_schema.get("additionalProperties") is False, name
    # FastMCP 4.x는 출력 스키마의 $ref를 인라인으로 풀어 내보내므로 하위 모델은 pydantic 스키마로 확인
    defs = FilingDiff.model_json_schema()["$defs"] | SearchFilingsResult.model_json_schema()["$defs"] \
        | AnalysisMemoResult.model_json_schema()["$defs"]
    for model, required in REQUIRED_05_DEFS.items():
        assert required <= set(defs[model]["required"]), model
    change_schema = tools["get_filing_diff"].output_schema["properties"]["changes"]["items"]
    assert set(change_schema["required"]) == REQUIRED_05_DEFS["Change"]
    assert tools["get_filing_diff"].input_schema["properties"]["correction_rcept_no"]["pattern"] == r"^\d{14}$"
    assert tools["search_filings"].annotations.read_only_hint is True
    # save_review_decision은 LLM 바인딩 목록에서 빼도록 태그로 표시
    assert "no_llm_binding" in tools["save_review_decision"].meta["fastmcp"]["tags"]
    assert tools["save_review_decision"].annotations.read_only_hint is False


# ── search_filings ───────────────────────────────────────────────────────


async def test_search_filings_corrections_only(client):
    data = await call_ok(client, "search_filings", {"corp": "000001", "date_from": "2026-01-01",
                                                    "date_to": "2026-10-20", "corrections_only": True})
    res = SearchFilingsResult.model_validate(data)
    assert res.status == "ok" and res.company.corp_code == "00000001" and res.company.match_type == "stock_code"
    assert [f.rcept_no for f in res.filings] == ["20260312000123"]
    f = res.filings[0]
    assert f.is_correction and f.correction_tags == ["기재정정"] and f.base_report_nm == "단일판매ㆍ공급계약체결"
    assert f.dart_url.endswith("rcpNo=20260312000123")
    assert res.total_count == 4  # 필터 적용 전
    assert res.meta.source == "mock" and res.meta.warnings[0] == MOCK_WARNING


async def test_search_filings_keyword_limit_and_flags(client):
    res = SearchFilingsResult.model_validate(await call_ok(
        client, "search_filings", {"corp": "가상화학", "date_from": "2026-01-01", "date_to": "2026-10-20",
                                   "keyword": "전환사채", "limit": 2}))
    assert len(res.filings) == 2 and res.truncated
    original = SearchFilingsResult.model_validate(await call_ok(
        client, "search_filings", {"corp": "00000002", "date_from": "2026-04-01", "date_to": "2026-04-01"})).filings[0]
    assert original.rcept_no == "20260401000210" and not original.is_correction and original.has_later_correction


async def test_search_filings_ambiguous_company(client):
    res = SearchFilingsResult.model_validate(await call_ok(client, "search_filings", {"corp": "예시"}))
    assert res.status == "ambiguous_company" and res.company is None and res.filings == []
    assert [c.corp_code for c in res.company_candidates] == ["00000001", "00000004"]  # 상장사 우선


async def test_search_filings_no_data_is_not_error(client):  # T6
    res = SearchFilingsResult.model_validate(await call_ok(
        client, "search_filings", {"corp": "가상화학", "date_from": "2026-07-01", "date_to": "2026-08-01"}))
    assert res.status == "ok" and res.filings == [] and res.total_count == 0


async def test_search_filings_errors(client):
    e = await call_err(client, "search_filings", {"corp": "000002", "date_from": "2026-05-01", "date_to": "2026-01-01"})
    assert e.error.code == "INVALID_ARGUMENT" and e.error.details == {"date_from": "2026-05-01", "date_to": "2026-01-01"}
    assert (await call_err(client, "search_filings", {"corp": "없는회사"})).error.code == "COMPANY_NOT_FOUND"
    e = await call_err(client, "search_filings", {"corp": "예시전자", "limit": 0})
    assert e.error.code == "INVALID_ARGUMENT" and e.error.details["errors"][0]["loc"] == "limit"


# ── get_filing_diff ──────────────────────────────────────────────────────


async def test_get_filing_diff_simple(client):  # T2, T3
    diff = FilingDiff.model_validate(await call_ok(client, "get_filing_diff", {"correction_rcept_no": "20260312000123"}))
    assert diff.diff_id == "20260312000123:diff-0.1.0"
    assert diff.match.status == "matched" and diff.match.original_rcept_no == "20260305000045"
    assert diff.match.confidence >= 0.8 and not diff.match.needs_review
    c1 = diff.changes[0]
    assert (c1.change_id, c1.field_key, c1.change_type) == ("20260312000123:c1", "contract_amount", "modified")
    assert (c1.before.value, c1.after.value, c1.after.unit) == (12_000_000_000, 15_600_000_000, "KRW")
    assert c1.delta.abs == 3_600_000_000 and c1.delta.pct == 30.0
    assert c1.evidence[0].role == "correction_table" and c1.evidence[0].row_index == 1
    assert c1.evidence[0].dart_url == "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260312000123"
    c2 = diff.changes[1]
    assert c2.value_type == "date_range" and str(c2.after.end) == "2027-06-30"
    assert diff.summary.total == 3 and not diff.needs_review
    assert diff.meta.engine_version == "diff-0.1.0" and diff.meta.source == "mock"


async def test_get_filing_diff_second_correction_chain(client):  # T8 (2차 정정)
    diff = FilingDiff.model_validate(await call_ok(client, "get_filing_diff", {"correction_rcept_no": "20260415000301"}))
    m = diff.match
    assert m.status == "matched" and m.original_rcept_no == "20260401000210"
    assert m.previous_rcept_no == "20260408000155" != m.original_rcept_no
    assert [c.rcept_no for c in m.chain] == ["20260401000210", "20260408000155", "20260415000301"]
    by_key = {c.field_key: c for c in diff.changes}
    assert by_key["offering_amount"].after.value == 40_000_000_000  # 표 단위 백만원
    assert by_key["conversion_price"].after.unit == "KRW_PER_SHARE"
    assert by_key["conversion_period"].extraction.method == "correction_footnote"
    assert by_key["fund_purpose_operating"].change_type == "added"
    unresolved = diff.changes[-1]
    assert unresolved.needs_review and unresolved.review_reasons == ["FOOTNOTE_UNRESOLVED"]
    assert unresolved.regulator_ordered is True
    assert diff.needs_review and diff.summary.needs_review_count == 1


async def test_get_filing_diff_ambiguous(client):  # T8 (모호)
    diff = FilingDiff.model_validate(await call_ok(client, "get_filing_diff", {"correction_rcept_no": "20260617000088"}))
    assert diff.match.status == "ambiguous" and diff.match.original_rcept_no is None
    assert [c.rcept_no for c in diff.match.candidates] == ["20260610000101", "20260610000102"]
    assert all("MATCH_UNCERTAIN" in c.review_reasons for c in diff.changes) and diff.needs_review


async def test_get_filing_diff_user_specified(client):
    diff = FilingDiff.model_validate(await call_ok(
        client, "get_filing_diff", {"correction_rcept_no": "20260617000088", "original_rcept_no": "20260610000101"}))
    assert diff.match.status == "user_specified" and diff.match.original_rcept_no == "20260610000101"
    assert diff.match.previous_rcept_no == "20260610000101"  # 같은 날 다른 원본(…102)은 직전본이 아님


async def test_get_filing_diff_errors(client):
    e = await call_err(client, "get_filing_diff", {"correction_rcept_no": "20260305000045"})  # T4
    assert e.error.code == "NOT_A_CORRECTION" and e.error.retryable is False
    assert e.error.details["has_later_correction"] is True

    dart = providers.get_dart_core()
    dart.calls.clear()
    e = await call_err(client, "get_filing_diff", {"correction_rcept_no": "123"})  # T5
    assert e.error.code == "INVALID_ARGUMENT" and dart.calls == []  # 데이터 공급원 호출 0회

    assert (await call_err(client, "get_filing_diff", {"correction_rcept_no": "20990101000001"})).error.code \
        == "FILING_NOT_FOUND"
    e = await call_err(client, "get_filing_diff", {"correction_rcept_no": "20260312000123",
                                                   "original_rcept_no": "20260210000077"})
    assert e.error.code == "INVALID_ARGUMENT" and e.error.details["failed_signals"] == ["S2_title"]
    e = await call_err(client, "get_filing_diff", {"correction_rcept_no": "20260312000123", "unknown": 1})
    assert e.error.code == "INVALID_ARGUMENT"


# ── get_analysis_memo ────────────────────────────────────────────────────


async def test_get_analysis_memo_by_corp_and_source(client):
    res = AnalysisMemoResult.model_validate(await call_ok(
        client, "get_analysis_memo", {"corp_code": "00000001", "source_rcept_no": "20260305000045"}))
    assert [m.memo_id for m in res.memos] == ["6f1c2e0a-0000-4000-8000-000000000001"]
    memo = res.memos[0]
    assert memo.version == 3 and [s.section_id for s in memo.sections] == ["s1", "s2", "s3"]
    all_memos = AnalysisMemoResult.model_validate(await call_ok(client, "get_analysis_memo", {"corp_code": "00000001"}))
    assert len(all_memos.memos) == 2
    none = AnalysisMemoResult.model_validate(await call_ok(client, "get_analysis_memo", {"corp_code": "00000005"}))
    assert none.memos == []


async def test_get_analysis_memo_by_id_and_version(client):
    res = AnalysisMemoResult.model_validate(await call_ok(client, "get_analysis_memo", {
        "memo_id": "6f1c2e0a-0000-4000-8000-000000000001", "version": 2, "include_sections": False}))
    assert res.memos[0].version == 2 and res.memos[0].sections is None


async def test_get_analysis_memo_errors(client):
    e = await call_err(client, "get_analysis_memo", {})
    assert e.error.code == "INVALID_ARGUMENT" and e.error.message == "memo_id 또는 corp_code 중 하나는 필요합니다."
    e = await call_err(client, "get_analysis_memo", {"memo_id": "6f1c2e0a-0000-4000-8000-0000000000ff"})
    assert e.error.code == "MEMO_NOT_FOUND"
    e = await call_err(client, "get_analysis_memo", {"memo_id": "6f1c2e0a-0000-4000-8000-000000000001", "version": 9})
    assert e.error.code == "MEMO_NOT_FOUND"
    e = await call_err(client, "get_analysis_memo", {"memo_id": "not-a-uuid"})
    assert e.error.code == "INVALID_ARGUMENT"


# ── 미구현 Tool ──────────────────────────────────────────────────────────


async def test_not_implemented_tools(client):
    e = await call_err(client, "get_filing_document", {"rcept_no": "20260312000123"})
    assert e.error.code == "NOT_IMPLEMENTED"
    e = await call_err(client, "get_filing_document", {"rcept_no": "20260312000123", "view": "section"})
    assert e.error.code == "INVALID_ARGUMENT"
    args = {"idempotency_key": "0b7d0000-0000-4000-8000-000000000001", "memo_id": "6f1c2e0a-0000-4000-8000-000000000001",
            "base_version": 3, "correction_rcept_no": "20260312000123", "change_ids": ["20260312000123:c1"],
            "decision": "rejected", "reviewer_id": "ra_kim"}
    assert (await call_err(client, "save_review_decision", args)).error.code == "NOT_IMPLEMENTED"
    e = await call_err(client, "save_review_decision", args | {"decision": "approved"})
    assert e.error.code == "INVALID_ARGUMENT"
