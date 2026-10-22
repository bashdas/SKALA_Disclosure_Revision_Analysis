import asyncio
from datetime import date
from io import BytesIO
import json
import zipfile
import httpx
import pytest
from app.catalog import DisclosureCatalog, parse_family
from app.client import OpenDartClient
from app.config import Settings
from app.errors import OpenDartError


def test_exact_family_excludes_attachment_and_retains_correction_dates():
    raw = '''<html><select id="family"><option value="null">선택</option><option value="rcpNo=20261020000001" title="공급계약">2026.10.20 공급계약</option><option value="rcpNo=20261021000001" title="공급계약">2026.10.21 [정정] 공급계약</option></select><select id="att"><option value="rcpNo=20261021000999">첨부</option></select></html>'''.encode()
    rows = parse_family(raw, "20261020000001")["items"]
    assert len(rows) == 2 and rows[1]["is_correction"] is True
    assert rows[1]["filed_at"] == "2026-10-21"
    with pytest.raises(ValueError):
        parse_family(raw, "20261020000999")


def test_company_cache_and_paged_disclosure_search():
    stream = BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('CORPCODE.xml', '<result><list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name><stock_code>005930</stock_code></list></result>')
    calls = []
    def handle(request):
        calls.append(request.url.path)
        if request.url.path.endswith('corpCode.xml'):
            return httpx.Response(200, content=stream.getvalue())
        assert request.url.params['last_reprt_at'] == 'N'
        assert request.url.params['page_no'] == '2'
        return httpx.Response(200, json={'status':'000','list':[{'corp_code':'00126380','corp_name':'삼성전자','rcept_no':'20261021000001','rcept_dt':'20261021','report_nm':'[기재정정]공급계약','rm':'정'}],'total_count':30,'total_page':2})
    async def check():
        async with OpenDartClient(Settings(_env_file=None, opendart_api_key='a'*40), transport=httpx.MockTransport(handle)) as client:
            catalog = DisclosureCatalog(client)
            assert (await catalog.search_companies('삼성'))['items'][0]['stock_code'] == '005930'
            assert (await catalog.search_companies(''))['total_count'] == 1
            assert (await catalog.search_companies('', offset=20))['items'] == []
            assert (await catalog.search_companies('00126380'))['items'][0]['company_name'] == '삼성전자'
            assert calls.count('/api/corpCode.xml') == 1
            page = await catalog.search_disclosures(None, date(2026,10,20),date(2026,10,21),2,'공급')
            assert page['items'][0]['is_correction'] and not page['has_more']
            assert page['next_page'] == 3 and page['total_count'] is None
            with pytest.raises(OpenDartError):
                await catalog.search_disclosures(None, date(2026,1,1),date(2026,10,21))
    asyncio.run(check())


def test_company_random_order_is_stable_across_pages_and_varies_by_visit():
    import time
    async def check():
        catalog = DisclosureCatalog(None)
        catalog.companies = [{"corp_code": str(i), "company_name": f"Company {i}", "stock_code": ""} for i in range(40)]
        catalog.loaded_at = time.monotonic()
        first = await catalog.search_companies("", seed="first")
        second = await catalog.search_companies("", offset=20, seed="first")
        repeated = await catalog.search_companies("", seed="first")
        another = await catalog.search_companies("", seed="another")
        assert first == repeated and first["items"] != another["items"]
        assert len({row["corp_code"] for row in first["items"] + second["items"]}) == 40
    asyncio.run(check())


def test_company_disclosures_accept_more_than_one_year():
    def handle(request):
        assert request.url.params["bgn_de"] == "20200101"
        return httpx.Response(200, json={"status": "013"})
    async def check():
        async with OpenDartClient(Settings(_env_file=None, opendart_api_key='a'*40), transport=httpx.MockTransport(handle)) as client:
            result = await DisclosureCatalog(client).search_disclosures("00126380", date(2020, 1, 1), date(2026, 10, 22))
            assert result["items"] == [] and not result["has_more"]
    asyncio.run(check())


@pytest.mark.parametrize("query", ["20251014800059", " 20251014800059 "])
def test_receipt_search_limits_date_and_stops_after_exact_match(query):
    def handle(request):
        assert request.url.params["corp_code"] == "00398701"
        assert request.url.params["bgn_de"] == request.url.params["end_de"] == "20251014"
        return httpx.Response(200, json={"status": "000", "total_count": 30, "total_page": 2,
            "list": [{"corp_code": "00398701", "corp_name": "엘앤에프", "rcept_no": "20251014800059",
                "rcept_dt": "20251014", "report_nm": "풍문또는보도에대한해명", "rm": ""}]})

    async def check():
        async with OpenDartClient(Settings(_env_file=None, opendart_api_key='a'*40), transport=httpx.MockTransport(handle)) as client:
            result = await DisclosureCatalog(client).search_disclosures("00398701", date(1999, 1, 1), date(2026, 10, 22), query=query)
            assert [r["receipt_no"] for r in result["items"]] == ["20251014800059"]
            assert result["total_count"] == 1 and result["has_more"] is False
            assert result["items"][0]["filed_at"] == "2025-10-14"
    asyncio.run(check())


def test_receipt_search_checks_later_pages_on_the_same_date():
    calls = []
    def handle(request):
        page = int(request.url.params["page_no"])
        calls.append(page)
        assert request.url.params["bgn_de"] == request.url.params["end_de"] == "20251014"
        return httpx.Response(200, json={"status": "000", "total_count": 21, "total_page": 2,
            "list": [{"corp_code": "00398701", "corp_name": "엘앤에프",
                "rcept_no": "20251014800059" if page == 2 else "20251014800001",
                "rcept_dt": "20251014", "report_nm": "주요사항보고서", "rm": ""}]})

    async def check():
        async with OpenDartClient(Settings(_env_file=None, opendart_api_key='a'*40), transport=httpx.MockTransport(handle)) as client:
            catalog = DisclosureCatalog(client)
            first = await catalog.search_disclosures("00398701", date(1999, 1, 1), date(2026, 10, 22), query="20251014800059")
            assert first["items"] == [] and first["has_more"] is True
            assert first["next_page"] == 2 and first["total_count"] is None
            second = await catalog.search_disclosures("00398701", date(1999, 1, 1), date(2026, 10, 22), page=2, query="20251014800059")
            assert len(second["items"]) == 1 and second["has_more"] is False
            assert second["total_count"] == 1 and calls == [1, 2]
    asyncio.run(check())


@pytest.mark.parametrize("query", ["20251014800059", "20251340800059"])
def test_receipt_search_preserves_date_filters_without_external_calls(query):
    def handle(request):
        pytest.fail("An invalid or out-of-range receipt must not call OpenDART")

    async def check():
        async with OpenDartClient(Settings(_env_file=None, opendart_api_key='a'*40), transport=httpx.MockTransport(handle)) as client:
            result = await DisclosureCatalog(client).search_disclosures("00398701", date(2026, 1, 1), date(2026, 10, 22), query=query)
            assert result == {"items": [], "total_count": 0, "has_more": False}
    asyncio.run(check())


@pytest.mark.parametrize("query, expected", [("800059", 1), ("풍문", 1), ("엘앤에프", 1), ("없는공시", 0)])
def test_partial_receipt_and_existing_name_search_keep_pagination(query, expected):
    def handle(request):
        assert request.url.params["bgn_de"] == "19990101"
        assert request.url.params["end_de"] == "20261022"
        return httpx.Response(200, json={"status": "000", "total_count": 1, "total_page": 1,
            "list": [{"corp_code": "00398701", "corp_name": "엘앤에프", "rcept_no": "20251014800059",
                "rcept_dt": "20251014", "report_nm": "풍문또는보도에대한해명", "rm": ""}]})

    async def check():
        async with OpenDartClient(Settings(_env_file=None, opendart_api_key='a'*40), transport=httpx.MockTransport(handle)) as client:
            result = await DisclosureCatalog(client).search_disclosures("00398701", date(1999, 1, 1), date(2026, 10, 22), query=query)
            assert len(result["items"]) == expected and result["has_more"] is False
    asyncio.run(check())
