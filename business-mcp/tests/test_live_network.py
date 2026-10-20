"""[실제 네트워크] OpenDART 실조회 테스트 — 명시적 opt-in일 때만 실행합니다.

    RUN_LIVE_OPENDART=1 uv run pytest tests/test_live_network.py -v
키는 프로젝트 .env 또는 환경변수 OPENDART_API_KEY에서 읽고, 출력하지 않습니다. 호출 한도를 씁니다(약 20~40건).
기대값은 tests/fixtures/real/golden.json(사람이 DART 뷰어에서 확인한 값)입니다.
"""

import json
import os
from pathlib import Path

import pytest

from business_mcp import providers
from business_mcp.services.diff import get_filing_diff
from business_mcp.services.filings import search_filings

pytestmark = pytest.mark.skipif(os.environ.get("RUN_LIVE_OPENDART") != "1",
                                reason="실제 OpenDART 호출은 RUN_LIVE_OPENDART=1일 때만 실행")
GOLDEN = {c["id"]: c for c in json.loads(
    (Path(__file__).parent / "fixtures" / "real" / "golden.json").read_text(encoding="utf-8"))["cases"]}


@pytest.fixture
async def live(monkeypatch, tmp_path):
    monkeypatch.setenv("BUSINESS_MCP_ENV_FILE", ".env")  # 이 테스트만 프로젝트 .env의 키를 읽음
    monkeypatch.setenv("DATA_BACKEND", "live")
    monkeypatch.setenv("DART_DATA_DIR", str(tmp_path))
    providers.reset()
    if problem := providers.api_key_problem():
        pytest.skip(problem)
    yield providers.get_dart_core()
    await providers.aclose()
    providers.reset()


async def test_real_search_and_document_zip_structure(live):
    res = await search_filings(live, "S-Oil", corrections_only=True)
    assert res.status == "ok" and res.company.corp_code == "00138279" and res.meta.source == "opendart"
    doc = await live.ingest_filing(GOLDEN["A"]["correction"])
    # 실제 document.xml ZIP 구조 확인 (뷰어 HTML 기반 fixture가 다루지 못한 부분)
    print("files:", doc.files, "parse_warnings:", doc.parse_warnings)
    assert doc.correction is not None and doc.correction.items, "실제 ZIP에서 정정사항 표를 찾지 못함"


@pytest.mark.parametrize("case_id", ["A", "C1", "B"])
async def test_real_diff_matches_golden(live, case_id):
    case = GOLDEN[case_id]
    diff = await get_filing_diff(live, case["correction"])
    assert diff.match.original_rcept_no == case["expected_original"]
    for exp in case["changes"]:
        if "before" not in exp:
            continue
        c = next(x for x in diff.changes if x.field_key == exp.get("field_key", x.field_key)
                 and x.field_label == exp.get("field_label", x.field_label))
        assert (c.before.value, c.after.value) == (exp["before"], exp["after"]), exp["location"]


async def test_real_long_chains(live):
    c2, c3 = GOLDEN["C2"], GOLDEN["C3"]
    diff = await get_filing_diff(live, c2["correction"])  # 원본까지 3단계 추적 (실제 원문으로 사람이 확인한 체인)
    assert [c.rcept_no for c in diff.match.chain] == c2["full_chain"]["expected_chain"]
    assert diff.match.original_rcept_no == c2["full_chain"]["expected_original"]
    diff = await get_filing_diff(live, c3["correction"])  # 앞 버전 후보 2건에서 중단
    assert diff.match.original_rcept_no is None and diff.needs_review
    assert [c.rcept_no for c in diff.match.chain] == c3["full_chain"]["expected_chain"]
