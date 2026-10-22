import asyncio
import httpx
import pytest
from app.config import Settings
from app.parser import OpenDartDocumentParser
from app.sec import disclosure, search_company, search_filings

ID = 'SEC:1071739:0001071739-25-000185'
PREFIX = '/Archives/edgar/data/1071739/000107173925000185/'


def handler(request):
    assert request.url.host in {'www.sec.gov', 'data.sec.gov'}
    if request.url.host == 'data.sec.gov':
        return httpx.Response(200, json={'cik':1071739, 'name':'CENTENE CORP', 'tickers':['CNC'],
            'filings':{'recent':{'accessionNumber':['0001071739-25-000185'], 'filingDate':['2025-10-29'], 'form':['8-K']}}})
    if request.url.path.endswith('-index.html'):
        return httpx.Response(200, text=f'''<html><body><span class="companyName">CENTENE CORP (Filer)</span>
<div>Filing Date</div><div>2025-10-29</div><table class="tableFile">
<tr><td>1</td><td>report</td><td><a href="{PREFIX}report.htm">report</a></td><td>8-K</td></tr>
<tr><td>2</td><td>results</td><td><a href="{PREFIX}results.htm">results</a></td><td>EX-99.1</td></tr>
</table></body></html>''')
    return httpx.Response(200, text='<html><body><ix:header>hidden metadata</ix:header><p>$6.7 billion non-cash goodwill impairment</p></body></html>')


def test_sec_originals_company_and_search():
    settings=Settings(_env_file=None)
    transport=httpx.MockTransport(handler)
    result=asyncio.run(disclosure(ID, OpenDartDocumentParser(), settings, transport))
    assert result['corp_code'] is None and result['filed_at']=='2025-10-29'
    assert result['source']['provider']=='SEC' and len(result['document']['files'])==2
    assert '$6.7 billion' in result['document']['text']
    assert 'hidden metadata' not in result['document']['text']
    assert asyncio.run(search_company('SEC:1071739',settings,transport))['items'][0]['stock_code']=='CNC'
    from datetime import date
    page=asyncio.run(search_filings('SEC:1071739',date(2025,10,29),date(2025,10,29),1,'8-K',settings,transport))
    assert page['items'][0]['receipt_no']==ID
    with pytest.raises(Exception):
        asyncio.run(disclosure('SEC:../../etc:0001071739-25-000185',OpenDartDocumentParser(),settings,transport))


def test_sec_amendment_keeps_official_form_type():
    def amended(request):
        response = handler(request)
        if request.url.path.endswith('-index.html'):
            return httpx.Response(200, text=response.text.replace('>8-K<', '>8-K/A<'))
        return response
    result = asyncio.run(disclosure(ID, OpenDartDocumentParser(), Settings(_env_file=None), httpx.MockTransport(amended)))
    assert result['report_name'].startswith('8-K/A ')
