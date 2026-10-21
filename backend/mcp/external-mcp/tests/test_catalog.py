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
