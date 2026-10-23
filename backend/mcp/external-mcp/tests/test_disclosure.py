import asyncio
from io import BytesIO
import json
import logging
import zipfile

import httpx
import pytest
from fastapi.testclient import TestClient

from app.client import OpenDartClient
from app.config import Settings
from app.errors import OpenDartError
from app.main import create_app
from app.parser import OpenDartDocumentParser

KEY = "test-only-" + "a" * 30
assert len(KEY) == 40
RECEIPT = "20261020000123"
HEADERS = {"Accept": "application/json, text/event-stream", "Host": "localhost:8083"}
XML = '''<?xml version="1.0" encoding="UTF-8"?>
<DOCUMENT><DOCUMENT-NAME>정정신고 보고서</DOCUMENT-NAME><SECTION-1><TITLE>정정사항</TITLE>
<P>한국어 원문 계약금액 검토</P><TABLE><TR><TH>항목</TH><TH>정정 전</TH><TH>정정 후</TH></TR>
<TR><TD ROWSPAN="2">계약금액</TD><TD>100억원</TD><TD>120억원</TD></TR>
<TR><TD COLSPAN="2">추가 설명</TD></TR></TABLE><P>끝 문단</P></SECTION-1></DOCUMENT>'''.encode()
ROW = {"rcept_no": RECEIPT, "corp_code": "00123456", "corp_name": "테스트기업", "report_nm": "[기재정정]단일판매ㆍ공급계약체결", "rcept_dt": "20261020"}


def archive(data=XML, filename="document.xml"):
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as output:
        output.writestr(filename, data)
    return stream.getvalue()


def settings(**extra):
    return Settings(_env_file=None, opendart_api_key=KEY, **extra)


def rpc(client, receipt=RECEIPT):
    response = client.post("/mcp", headers=HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_disclosure", "arguments": {"receipt_no": receipt}}})
    assert response.status_code == 200
    return response.json()["result"]


def success_handler(request):
    assert request.url.params["crtfc_key"] == KEY
    if request.url.path.endswith("/document.xml"):
        assert request.url.params["rcept_no"] == RECEIPT
        return httpx.Response(200, content=archive(), headers={"Content-Type": "application/zip"})
    assert request.url.path.endswith("/list.json")
    assert request.url.params["bgn_de"] == request.url.params["end_de"] == "20261020"
    assert request.url.params["last_reprt_at"] == "N"
    assert request.url.params["page_count"] == "100"
    assert "rcept_no" not in request.url.params
    return httpx.Response(200, json={"status": "000", "total_page": 1, "list": [ROW]})


def test_server_initialize_health_and_single_tool():
    with TestClient(create_app(settings())) as client:
        assert client.get("/health").json() == {"status": "ok", "service": "external-mcp"}
        initialized = client.post("/mcp", headers=HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "1"}}})
        assert initialized.status_code == 200 and "serverInfo" in initialized.json()["result"]
        listing = client.post("/mcp", headers=HEADERS, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = listing.json()["result"]["tools"]
        assert {tool["name"] for tool in tools} == {"get_disclosure", "search_academic_papers", "get_financial_statements", "opendart_search_companies", "opendart_search_disclosures", "opendart_get_disclosure_family", "naver_news_headlines", "read_naver_news_article"}
        tools = [tool for tool in tools if tool["name"] == "get_disclosure"]
        assert set(tools[0]["inputSchema"]["properties"]) == {"receipt_no"}


def test_disclosure_metadata_korean_order_tables_and_key_safety(caplog):
    caplog.set_level(logging.INFO, logger="httpx")
    with TestClient(create_app(settings(), transport=httpx.MockTransport(success_handler))) as client:
        result = rpc(client)
    assert not result.get("isError", False)
    data = result["structuredContent"]
    assert data["receipt_no"] == RECEIPT and data["corp_code"] == ROW["corp_code"]
    assert data["company_name"] == "테스트기업" and data["report_name"] == ROW["report_nm"]
    assert data["filed_at"] == "2026-10-20" and data["metadata_status"] == "FOUND"
    document = data["document"]
    assert document["document_id"] is None and "한국어 원문" in document["text"]
    assert document["text"].index("정정사항") < document["text"].index("정정 전") < document["text"].index("끝 문단")
    rows = document["tables"][0]["rows"]
    assert [cell["text"] for cell in rows[0]["cells"]] == ["항목", "정정 전", "정정 후"]
    assert rows[1]["cells"][0]["rowspan"] == 2 and rows[2]["cells"][0]["colspan"] == 2
    assert any(block["type"] == "section" for block in document["blocks"])
    assert data["source"]["original_location"] == f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={RECEIPT}"
    assert data["source"]["published_at"] == data["filed_at"]
    assert KEY not in str(result) and KEY not in caplog.text
    assert "[REDACTED]" in caplog.text and "한국어 원문" not in caplog.text


@pytest.mark.parametrize("status,code", [("013", "DISCLOSURE_NOT_FOUND"), ("014", "DISCLOSURE_NOT_FOUND"), ("010", "OPENDART_AUTH_FAILED"), ("011", "OPENDART_AUTH_FAILED"), ("012", "OPENDART_AUTH_FAILED"), ("901", "OPENDART_AUTH_FAILED"), ("020", "OPENDART_RATE_LIMITED"), ("800", "OPENDART_UNAVAILABLE"), ("900", "OPENDART_UNAVAILABLE")])
def test_official_xml_error_codes(status, code):
    response = f"<result><status>{status}</status><message>{KEY}</message></result>".encode()
    with TestClient(create_app(settings(), transport=httpx.MockTransport(lambda _: httpx.Response(200, content=response)))) as client:
        result = rpc(client)
    assert result["isError"] and code in str(result) and KEY not in str(result)


@pytest.mark.parametrize("error,code", [(httpx.ReadTimeout, "OPENDART_TIMEOUT"), (httpx.ConnectError, "OPENDART_UNAVAILABLE")])
def test_transport_failure(error, code, caplog):
    def handler(request):
        raise error("diagnostic " + KEY, request=request)
    with TestClient(create_app(settings(), transport=httpx.MockTransport(handler))) as client:
        result = rpc(client)
    assert result["isError"] and code in str(result)
    assert KEY not in str(result) and KEY not in caplog.text


@pytest.mark.parametrize("receipt", ["", "123", "2026102000012x", "２０２６１０２００００１２３", "20261020000123\n"])
def test_invalid_receipt_no_without_network(receipt):
    def handler(_):
        pytest.fail("Invalid receipt must not call API")
    with TestClient(create_app(settings(), transport=httpx.MockTransport(handler))) as client:
        result = rpc(client, receipt)
    assert result["isError"] and "INVALID_RECEIPT_NO" in str(result)


@pytest.mark.parametrize("raw", [b"PKnot-a-real-zip", archive(b"<DOCUMENT><P>broken"), archive(b"garbage"), archive(b"")])
def test_malformed_documents(raw):
    with TestClient(create_app(settings(), transport=httpx.MockTransport(lambda _: httpx.Response(200, content=raw)))) as client:
        result = rpc(client)
    assert result["isError"] and "DISCLOSURE_PARSE_FAILED" in str(result)


def test_explicit_euckr_and_html_parsing():
    xml = '<?xml version="1.0" encoding="EUC-KR"?><DOCUMENT><TITLE>정정사항</TITLE><P>한글&nbsp;원문</P></DOCUMENT>'.encode("euc-kr")
    assert "한글 원문" in OpenDartDocumentParser().parse(archive(xml))["text"]
    html = '<html><body><h1>정정 보고</h1><p>첫째<br>둘째</p><script>do not include</script><table><tr><td>정정 전</td><td>정정 후</td></tr></table></body></html>'.encode()
    result = OpenDartDocumentParser().parse(archive(html, "document.html"))
    assert "첫째\n둘째" in result["text"] and "do not include" not in result["text"]
    assert result["tables"][0]["rows"][0]["cells"][1]["text"] == "정정 후"


def test_metadata_exact_match_pagination_and_no_guessed_date():
    pages = []
    def handler(request):
        if request.url.path.endswith("document.xml"):
            return httpx.Response(200, content=archive())
        page = int(request.url.params["page_no"])
        pages.append(page)
        return httpx.Response(200, json={"status": "000", "total_page": 2,
            "list": [{**ROW, "rcept_no": "20261020999999"}] if page == 1 else [{**ROW, "rcept_dt": "20261021"}]})
    with TestClient(create_app(settings(), transport=httpx.MockTransport(handler))) as client:
        result = rpc(client)["structuredContent"]
    assert pages == [1, 2] and result["filed_at"] == "2026-10-21"


@pytest.mark.parametrize("payload,status", [({"status": "013"}, "NOT_FOUND"), ({"status": "000", "total_page": 1, "list": []}, "NOT_FOUND"), ({"status": "000", "total_page": 2, "list": []}, "SEARCH_LIMIT_REACHED")])
def test_original_available_but_metadata_missing_stays_null(payload, status):
    def handler(request):
        return httpx.Response(200, content=archive()) if request.url.path.endswith("document.xml") else httpx.Response(200, json=payload)
    with TestClient(create_app(settings(opendart_metadata_max_pages=1), transport=httpx.MockTransport(handler))) as client:
        result = rpc(client)
    assert not result.get("isError", False)
    data = result["structuredContent"]
    assert data["metadata_status"] == status
    assert data["corp_code"] is data["company_name"] is data["report_name"] is data["filed_at"] is None
    assert data["source"]["published_at"] is None


def test_metadata_transport_failure_not_silently_treated_as_absence():
    def handler(request):
        if request.url.path.endswith("document.xml"):
            return httpx.Response(200, content=archive())
        raise httpx.ReadTimeout("private " + KEY, request=request)
    with TestClient(create_app(settings(), transport=httpx.MockTransport(handler))) as client:
        result = rpc(client)
    assert result["isError"] and "OPENDART_TIMEOUT" in str(result)


def test_parser_entity_and_zip_limits():
    for xml in [b'<!DOCTYPE DOCUMENT [<!ENTITY x SYSTEM "file:///etc/passwd">]><DOCUMENT><P>&x;</P></DOCUMENT>', b'<DOCUMENT><P>&undefined;</P></DOCUMENT>']:
        with pytest.raises(OpenDartError) as failure:
            OpenDartDocumentParser().parse(archive(xml))
        assert failure.value.code == "DISCLOSURE_PARSE_FAILED"
    parser = OpenDartDocumentParser()
    parser.MAX_MEMBER = 10
    with pytest.raises(OpenDartError):
        parser.parse(archive())


def test_client_lifecycle_and_unconfigured_key():
    async def run():
        client = OpenDartClient(settings(), transport=httpx.MockTransport(success_handler))
        async with client:
            http = client._http
            await client.get_document(RECEIPT)
            await client.find_metadata(RECEIPT)
            assert client._http is http and not http.is_closed
        assert http.is_closed and client._http is None
    asyncio.run(run())
    with TestClient(create_app(Settings(_env_file=None, opendart_api_key=""))) as client:
        assert client.get("/health").status_code == 200
        assert "OPENDART_AUTH_FAILED" in str(rpc(client))


@pytest.mark.parametrize("http_status,code", [(401, "OPENDART_AUTH_FAILED"), (403, "OPENDART_AUTH_FAILED"), (429, "OPENDART_RATE_LIMITED"), (503, "OPENDART_UNAVAILABLE"), (404, "OPENDART_UNAVAILABLE"), (302, "OPENDART_UNAVAILABLE")])
def test_http_failure_is_not_a_successful_empty_lookup(http_status, code):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(http_status, headers={"Location": "https://example.test/should-not-follow"})
    with TestClient(create_app(settings(), transport=httpx.MockTransport(handler))) as client:
        result = rpc(client)
    assert result["isError"] and code in str(result) and len(calls) == 1


@pytest.mark.parametrize("payload", ["broken-json", "[]", '{"status":"000","list":{}}'])
def test_malformed_metadata_is_failure_not_null_success(payload):
    def handler(request):
        return httpx.Response(200, content=archive()) if request.url.path.endswith("document.xml") else httpx.Response(200, text=payload)
    with TestClient(create_app(settings(), transport=httpx.MockTransport(handler))) as client:
        result = rpc(client)
    assert result["isError"] and "OPENDART_UNAVAILABLE" in str(result)


def test_upstream_document_cannot_echo_configured_key():
    raw = archive(f'<DOCUMENT><P>text {KEY}</P></DOCUMENT>'.encode())
    def handler(request):
        return httpx.Response(200, content=raw) if request.url.path.endswith("document.xml") else httpx.Response(200, json={"status": "013"})
    with TestClient(create_app(settings(), transport=httpx.MockTransport(handler))) as client:
        result = rpc(client)
    assert not result.get("isError", False) and KEY not in str(result)
    assert "[REDACTED]" in result["structuredContent"]["document"]["text"]


def test_paragraph_boundaries_inside_table_cells():
    xml = '<DOCUMENT><TABLE><TR><TD><P>정정 전 설명</P><P>다음 줄</P></TD></TR></TABLE></DOCUMENT>'.encode()
    data = OpenDartDocumentParser().parse(archive(xml))
    assert data["tables"][0]["rows"][0]["cells"][0]["text"] == "정정 전 설명\n다음 줄"


def test_literal_korean_angle_bracket_text_in_dart_table():
    xml = '<DOCUMENT><TABLE><TR><TD><시장성 없는 지분증권>(주1)</TD></TR></TABLE></DOCUMENT>'.encode()
    data = OpenDartDocumentParser().parse(archive(xml))
    assert data['tables'][0]['rows'][0]['cells'][0]['text'] == '<시장성 없는 지분증권>(주1)'


def test_dart_utf8_body_with_incorrect_euckr_declaration_and_literal_text():
    xml = '<?xml version="1.0" encoding="EUC-KR"?><DOCUMENT><P>한글 공시 <기업 전체의 Value / 금액: 1,000></P></DOCUMENT>'.encode('utf-8')
    assert '한글 공시 <기업 전체의 Value / 금액: 1,000>' in OpenDartDocumentParser().parse(archive(xml))['text']


def test_dart_html_body_in_xml_named_member():
    html = '<html><head><meta charset="EUC-KR"></head><body><p>정정공시 원문</p></body></html>'.encode('utf-8')
    result = OpenDartDocumentParser().parse(archive(html, '20261016800907.xml'))
    assert result['text'] == '정정공시 원문'
    assert result['files'][0]['content_type'] == 'text/html'
