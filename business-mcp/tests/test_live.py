"""LiveDartCore + 파일 캐시 + 고유번호 캐시 + provider/설정, 실제 공시 fixture의 MCP 재생 (네트워크 없음).

검증 수준 구분:
- [합성] 직접 만든 목록·응답으로 페이지 처리·캐시·오류 경로를 확인
- [재생] tests/fixtures/real의 실제 공시(DART 공개 뷰어 HTML + 공개 검색 행)를 가짜 OpenDART로 돌려 live 구현 전체를 확인.
  ZIP 포장과 list.json 응답은 재구성한 것이라 OpenDART 실제 응답 형식 검증을 대신하지 않습니다.
"""

import asyncio
import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from fake_opendart import FakeOpenDart, _zip
from fastmcp import Client

from business_mcp import providers
from business_mcp.schemas import MOCK_WARNING, ErrorResponse, FilingDiff, SearchFilingsResult
from business_mcp.server import mcp
from dart_core import live as live_module
from dart_core.client import DartClient
from dart_core.corp_codes import CorpCodeIndex
from dart_core.live import LiveDartCore
from dart_core.status import DartNotFound, DartUnavailable
from dart_core.store import FileStore

KEY = "A1" * 20
GOLDEN = {c["id"]: c for c in json.loads(
    (Path(__file__).parent / "fixtures" / "real" / "golden.json").read_text(encoding="utf-8"))["cases"]}


def build_core(tmp_path, transport, **kw) -> LiveDartCore:
    client = DartClient(KEY, transport=transport, retry_delays=(0, 0, 0))
    return LiveDartCore(client, FileStore(tmp_path), CorpCodeIndex(client, tmp_path / "corp_codes.json"), **kw)


@pytest.fixture
async def replay(tmp_path):
    fake = FakeOpenDart()
    core = build_core(tmp_path, fake.transport())
    yield core, fake
    await core.aclose()


@pytest.fixture
def isolated_settings():
    providers.reset()
    yield
    providers.reset()


# ── [합성] 목록 페이지·접수번호 조회 ────────────────────────────────────


def synthetic_rows(n: int, day: str = "20260105") -> list[dict]:
    return [{"corp_cls": "E", "corp_name": "[합성]회사", "corp_code": "99999999", "stock_code": "",
             "report_nm": "[합성]보고서", "rcept_no": f"{day}{i:06d}", "flr_nm": "x", "rcept_dt": day, "rm": ""}
            for i in range(n)]


def paging_transport(rows: list[dict], calls: list):
    def handler(request):
        q = request.url.params
        calls.append(dict(q))
        page, size = int(q["page_no"]), int(q["page_count"])
        chunk = rows[(page - 1) * size: page * size]
        return httpx.Response(200, json={"status": "000", "total_count": len(rows),
                                         "total_page": -(-len(rows) // size), "list": chunk})
    return httpx.MockTransport(handler)


async def test_list_filings_pages_dedup_truncation(tmp_path):
    rows = synthetic_rows(250)
    rows.insert(100, dict(rows[99]))  # 페이지 경계 중복 행
    calls = []
    core = build_core(tmp_path, paging_transport(rows, calls))
    metas, total = await core.list_filings("99999999", date(2026, 1, 1), date(2026, 1, 31), max_pages=2)
    assert total == 251 and len(calls) == 2 and len(metas) == 199  # 잘림을 total_count로 알 수 있음
    assert [m.rcept_no for m in metas] == sorted((m.rcept_no for m in metas), reverse=True)
    assert calls[0]["page_count"] == "100" and calls[0]["bgn_de"] == "20260101" and calls[0]["last_reprt_at"] == "N"
    assert core.store.get_meta(metas[0].rcept_no) == metas[0]
    await core.aclose()


async def test_list_filings_013_and_bad_rows(tmp_path):
    core = build_core(tmp_path, httpx.MockTransport(lambda r: httpx.Response(200, json={"status": "013"})))
    assert await core.list_filings("99999999", date(2026, 1, 1), date(2026, 1, 2)) == ([], 0)
    await core.aclose()
    bad = httpx.MockTransport(lambda r: httpx.Response(200, json={"status": "000", "total_count": 1, "total_page": 1,
                                                                  "list": [{"rcept_no": "x"}]}))
    core = build_core(tmp_path, bad)
    with pytest.raises(DartUnavailable):
        await core.list_filings("99999999", date(2026, 1, 1), date(2026, 1, 2))
    await core.aclose()


async def test_find_filing_scans_all_pages_of_the_day(tmp_path):
    rows = synthetic_rows(250)
    target = rows[230]["rcept_no"]
    calls = []
    core = build_core(tmp_path, paging_transport(rows, calls))
    meta = await core.find_filing(target)
    assert meta.rcept_no == target and len(calls) == 3 and "corp_code" not in calls[0]  # 첫 페이지에 없어도 계속
    calls.clear()
    assert (await core.find_filing(target)).rcept_no == target and calls == []  # 메타 캐시
    assert await core.find_filing("20260105999999") is None  # 하루 전체(3페이지)를 다 보고 없음 → 미존재
    assert await core.find_filing("99999999000001") is None  # 앞 8자리가 날짜가 아님
    await core.aclose()


async def test_find_filing_budget_exhausted_is_not_absence(tmp_path):
    core = build_core(tmp_path, paging_transport(synthetic_rows(250), []), find_max_pages=2)
    with pytest.raises(DartNotFound) as e:
        await core.find_filing("20260105999999")
    assert e.value.details["lookup_complete"] is False and e.value.details["pages_scanned"] == 2
    await core.aclose()


# ── [재생] 원문 캐시 ────────────────────────────────────────────────────


async def test_ingest_cache_reuse_and_concurrency(replay):
    core, fake = replay
    docs = await asyncio.gather(*(core.ingest_filing("20261019800110") for _ in range(5)))
    assert fake.document_downloads == {"20261019800110": 1} and all(d == docs[0] for d in docs)
    assert (await core.ingest_filing("20261019800110")) == docs[0] and fake.document_downloads["20261019800110"] == 1
    zip_path = core.store.root / "zips" / "20261019800110.zip"
    assert zip_path.exists() and (core.store.root / "zips" / "20261019800110.zip.sha256").exists()
    assert list((core.store.root / "parsed").glob("20261019800110.parser-*.json"))


async def test_ingest_corrupt_zip_redownloads_and_corrupt_parse_reparses(replay):
    core, fake = replay
    first = await core.ingest_filing("20261019800110")
    parsed = next((core.store.root / "parsed").glob("20261019800110.*.json"))
    parsed.write_text("{broken")
    assert await core.ingest_filing("20261019800110") == first and fake.document_downloads["20261019800110"] == 1
    (core.store.root / "zips" / "20261019800110.zip").write_bytes(b"PK\x03\x04tampered")
    assert await core.ingest_filing("20261019800110") == first and fake.document_downloads["20261019800110"] == 2


async def test_parser_version_change_reparses_from_cached_zip(replay, monkeypatch):
    core, fake = replay
    await core.ingest_filing("20261019800110")
    monkeypatch.setattr(live_module, "PARSER_VERSION", "parser-9.9.9")
    monkeypatch.setattr("dart_core.parsing.document.PARSER_VERSION", "parser-9.9.9")
    doc = await core.ingest_filing("20261019800110")
    assert doc.parser_version == "parser-9.9.9" and fake.document_downloads["20261019800110"] == 1


async def test_missing_document_is_filing_not_found(replay):
    core, _ = replay
    with pytest.raises(DartNotFound):
        await core.ingest_filing("20250923800143")


# ── 고유번호 캐시 ────────────────────────────────────────────────────────


async def test_corp_codes_lazy_ttl_stale_and_disk(tmp_path):
    fake = FakeOpenDart()
    fail = {"on": False}

    def handler(request):
        if fail["on"]:
            return httpx.Response(503)
        return fake.handler(request)

    now = {"t": 1_000_000.0}
    client = DartClient(KEY, transport=httpx.MockTransport(handler), retry_delays=(0, 0, 0))
    index = CorpCodeIndex(client, tmp_path / "corp_codes.json", ttl_seconds=3600, retry_backoff=600,
                          clock=lambda: now["t"])
    assert fake.requests == []  # 지연 로드
    results = await asyncio.gather(*(index.resolve("S-Oil") for _ in range(3)))
    assert all(hit.corp_code == "00138279" and hit.match_type == "exact" for hit, _ in results)
    assert len(fake.requests) == 1  # 동시 요청에도 한 번만 받음
    hit, _ = await index.resolve("동아")
    assert hit.corp_name == "동아지질" and hit.match_type == "prefix"
    now["t"] += 3601
    fail["on"] = True
    hit, _ = await index.resolve("리메드")  # 갱신 실패 → 기존 캐시 사용
    assert hit.corp_code == "01275665" and index.stale and "UPSTREAM_UNAVAILABLE" in index.last_error
    index2 = CorpCodeIndex(client, tmp_path / "corp_codes.json", ttl_seconds=10 ** 9, clock=lambda: now["t"])
    assert (await index2.resolve("00178754"))[0].corp_name == "동아지질"  # 디스크 캐시
    empty = CorpCodeIndex(client, tmp_path / "none.json", clock=lambda: now["t"])
    with pytest.raises(DartUnavailable):  # 캐시가 전혀 없으면 오류
        await empty.resolve("S-Oil")
    await client.aclose()


# ── [재생] MCP 계약 ─────────────────────────────────────────────────────


@pytest.fixture
async def live_mcp(replay, monkeypatch):
    core, fake = replay
    monkeypatch.setattr(providers, "_dart", core)
    async with Client(mcp) as c:
        yield c, fake


async def diff_of(client, rcept_no: str) -> tuple[FilingDiff, int]:
    r = await client.call_tool("get_filing_diff", {"correction_rcept_no": rcept_no}, raise_on_error=False)
    assert not r.is_error, r.content[0].text
    return FilingDiff.model_validate(r.structured_content), len(r.content[0].text.encode())


def assert_expected_changes(diff: FilingDiff, case: dict) -> None:
    for exp in case["changes"]:
        cands = [c for c in diff.changes
                 if ("field_key" not in exp or c.field_key == exp["field_key"])
                 and ("field_label" not in exp or c.field_label == exp["field_label"])
                 and ("change_type" not in exp or c.change_type == exp["change_type"])]
        assert cands, f"{case['id']}: {exp['location']} 없음"
        c = cands[0]
        if "before" in exp:
            assert c.before.value == exp["before"] and c.after.value == exp["after"], exp["location"]
        if "unit" in exp:
            assert c.after.unit == exp["unit"], exp["location"]
        assert c.evidence[0].role == "correction_table" and c.evidence[0].rcept_no == diff.correction.rcept_no
        assert c.evidence[0].dart_url.endswith(f"rcpNo={diff.correction.rcept_no}")


async def test_replay_search_filings(live_mcp):
    client, _ = live_mcp
    r = await client.call_tool("search_filings", {"corp": "S-Oil", "date_from": "2026-10-01", "date_to": "2026-10-20",
                                                  "corrections_only": True}, raise_on_error=False)
    res = SearchFilingsResult.model_validate(r.structured_content)
    assert res.status == "ok" and res.company.corp_code == "00138279"
    assert [f.rcept_no for f in res.filings] == ["20261019800117", "20261019800110"]
    assert all(f.is_correction and f.base_report_nm == "단일판매ㆍ공급계약체결" for f in res.filings)
    assert res.meta.source == "opendart" and MOCK_WARNING not in res.meta.warnings
    r = await client.call_tool("search_filings", {"corp": "S-Oil", "date_from": "2026-07-01", "date_to": "2026-08-01"})
    assert SearchFilingsResult.model_validate(r.structured_content).filings == []  # 013 → 정상 빈 결과


async def test_replay_case_a_single_hop_to_original(live_mcp):
    client, _ = live_mcp
    case = GOLDEN["A"]
    diff, size = await diff_of(client, case["correction"])
    assert diff.match.status == "matched" and diff.match.original_rcept_no == case["expected_original"]
    assert [c.rcept_no for c in diff.match.chain] == [case["expected_original"], case["correction"]]
    assert str(diff.correction_header.previous_filing_date) == "2026-10-19"  # 머리말 날짜 ≠ 원본 접수일
    assert_expected_changes(diff, case)
    assert diff.meta.source == "opendart" and size < 50_000


async def test_replay_case_c1_same_day_corrections_not_mixed(live_mcp):
    client, _ = live_mcp
    case = GOLDEN["C1"]
    diff, _ = await diff_of(client, case["correction"])
    chain = [c.rcept_no for c in diff.match.chain]
    assert diff.match.original_rcept_no == case["expected_original"] and not set(case["must_not_link"]) & set(chain)
    assert_expected_changes(diff, case)


async def test_replay_case_b_major_report(live_mcp):
    client, _ = live_mcp
    case = GOLDEN["B"]
    diff, size = await diff_of(client, case["correction"])
    assert diff.match.status == "matched" and diff.match.original_rcept_no == case["expected_original"]
    assert diff.match.confidence >= 0.8
    assert_expected_changes(diff, case)
    ids = [c.change_id for c in diff.changes]
    assert len(ids) == len(set(ids)) and "20261019000366:c3.1" in ids  # 셀 안 하위 항목 c{행}.{하위}
    unresolved = next(c for c in diff.changes if "FOOTNOTE_UNRESOLVED" in c.review_reasons)
    assert unresolved.needs_review and diff.needs_review
    assert size < 50_000


@pytest.mark.parametrize("case_id", ["C2", "C3"])
async def test_replay_long_chains_do_not_guess_original(live_mcp, case_id):
    client, _ = live_mcp
    case = GOLDEN[case_id]
    diff, _ = await diff_of(client, case["correction"])
    assert diff.match.status != "matched" and diff.match.original_rcept_no is None and diff.needs_review
    assert diff.match.previous_rcept_no == case["expected_previous"]
    chain = [c.rcept_no for c in diff.match.chain]
    assert chain == [case["expected_previous"], case["correction"]]
    assert not set(case.get("must_not_link", [])) & set(chain)
    assert all("MATCH_UNCERTAIN" in c.review_reasons for c in diff.changes)
    assert_expected_changes(diff, case)


async def test_replay_without_links_uses_dates_and_rejects_wrong_same_day_candidate(tmp_path, monkeypatch):
    fake = FakeOpenDart(strip_links=True)
    core = build_core(tmp_path, fake.transport())
    monkeypatch.setattr(providers, "_dart", core)
    async with Client(mcp) as client:
        diff, _ = await diff_of(client, "20261019800117")
        assert diff.match.original_rcept_no == "20251027800243"  # 머리말 날짜의 후보(…110)는 정정 전 값 불일치로 거부
        diff, _ = await diff_of(client, "20261019800483")
        assert diff.match.previous_rcept_no == "20260930800147"  # 같은 날 같은 제목 …801285가 아님
    await core.aclose()


async def test_replay_errors(live_mcp):
    client, _ = live_mcp
    r = await client.call_tool("get_filing_diff", {"correction_rcept_no": "20251223800740"}, raise_on_error=False)
    assert ErrorResponse.model_validate_json(r.content[0].text).error.code == "NOT_A_CORRECTION"
    r = await client.call_tool("get_filing_diff", {"correction_rcept_no": "20261019899999"}, raise_on_error=False)
    assert ErrorResponse.model_validate_json(r.content[0].text).error.code == "FILING_NOT_FOUND"


# ── provider·설정 ────────────────────────────────────────────────────────


async def test_live_mode_without_key_is_explicit(monkeypatch, isolated_settings):
    monkeypatch.setenv("DATA_BACKEND", "live")
    monkeypatch.delenv("OPENDART_API_KEY", raising=False)
    providers.reset()
    async with Client(mcp) as client:
        r = await client.call_tool("get_filing_diff", {"correction_rcept_no": "20261019800110"}, raise_on_error=False)
        err = ErrorResponse.model_validate_json(r.content[0].text).error
        assert err.code == "UPSTREAM_AUTH" and "OPENDART_API_KEY" in err.message
        r = await client.call_tool("get_analysis_memo", {"corp_code": "00138279"}, raise_on_error=False)
        assert ErrorResponse.model_validate_json(r.content[0].text).error.code == "NOT_IMPLEMENTED"


async def test_invalid_key_format_reported_without_value(monkeypatch, isolated_settings):
    bad = "not-a-valid-key-" + "z" * 10
    monkeypatch.setenv("DATA_BACKEND", "live")
    monkeypatch.setenv("OPENDART_API_KEY", bad)
    providers.reset()
    async with Client(mcp) as client:
        r = await client.call_tool("search_filings", {"corp": "S-Oil"}, raise_on_error=False)
    assert "형식" in r.content[0].text and bad not in r.content[0].text


async def test_live_mode_builds_live_core_with_key(monkeypatch, isolated_settings, tmp_path):
    monkeypatch.setenv("DATA_BACKEND", "live")
    monkeypatch.setenv("OPENDART_API_KEY", KEY)
    monkeypatch.setenv("DART_DATA_DIR", str(tmp_path))
    providers.reset()
    core = providers.get_dart_core()
    assert isinstance(core, LiveDartCore) and core.store.root == tmp_path and providers.get_dart_core() is core
    await providers.aclose()


@pytest.mark.parametrize("backend, key, code, status", [
    ("mock", None, 200, "ok"), ("live", None, 503, "misconfigured"), ("live", KEY, 200, "ok")])
async def test_health_semantics(monkeypatch, isolated_settings, backend, key, code, status):
    monkeypatch.setenv("DATA_BACKEND", backend)
    if key:
        monkeypatch.setenv("OPENDART_API_KEY", key)
    else:
        monkeypatch.delenv("OPENDART_API_KEY", raising=False)
    providers.reset()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mcp.http_app()), base_url="http://t") as h:
        r = await h.get("/health")
    assert r.status_code == code and r.json()["status"] == status and r.json()["upstream_checked"] is False
    assert KEY not in r.text


def test_zip_helper_is_real_zip():
    assert _zip("a.html", b"x")[:2] == b"PK"


# ── [재생-API] 실제 document.xml ZIP·list.json 스냅샷 (tests/fixtures/real/api, 2026-10-20 취득) ─────────


@pytest.fixture
async def api_mcp(tmp_path, monkeypatch):
    fake = FakeOpenDart(source="api")
    core = build_core(tmp_path, fake.transport())
    monkeypatch.setattr(providers, "_dart", core)
    async with Client(mcp) as c:
        yield c, fake
    await core.aclose()


@pytest.mark.parametrize("case_id", ["A", "C1", "B"])
async def test_api_zip_replay_matches_golden(api_mcp, case_id):
    client, _ = api_mcp
    case = GOLDEN[case_id]
    diff, size = await diff_of(client, case["correction"])
    assert diff.match.status == "matched" and diff.match.original_rcept_no == case["expected_original"]
    assert_expected_changes(diff, case)
    assert diff.meta.parser_version == "parser-0.1.1" and not diff.meta.warnings[:0] and size < 50_000


async def test_api_zip_replay_full_chain_to_original(api_mcp):  # C2: 원본까지 3단계 추적
    client, _ = api_mcp
    case = GOLDEN["C2"]
    diff, _ = await diff_of(client, case["correction"])
    full = case["full_chain"]
    assert diff.match.status == "matched" and diff.match.original_rcept_no == full["expected_original"]
    assert [c.rcept_no for c in diff.match.chain] == full["expected_chain"]
    assert diff.match.previous_rcept_no == case["expected_previous"] and not diff.needs_review
    assert_expected_changes(diff, case)


async def test_api_zip_replay_stops_when_previous_is_ambiguous(api_mcp):  # C3: 2026-08-31 후보 2건
    client, _ = api_mcp
    case = GOLDEN["C3"]
    diff, _ = await diff_of(client, case["correction"])
    full = case["full_chain"]
    chain = [c.rcept_no for c in diff.match.chain]
    assert diff.match.status != "matched" and diff.match.original_rcept_no is None and diff.needs_review
    assert chain == full["expected_chain"] and not set(full["must_not_link"]) & set(chain)
    assert diff.match.previous_rcept_no == case["expected_previous"]
