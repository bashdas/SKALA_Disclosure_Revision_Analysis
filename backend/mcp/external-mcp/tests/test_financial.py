import httpx
import pytest
from fastapi.testclient import TestClient
from test_disclosure import HEADERS, KEY, settings

from app.main import create_app


ARGS = {"corp_code": "00126380", "bsns_year": 2024, "reprt_code": "11011", "fs_div": "CFS"}
ROW = {"corp_code": "00126380", "bsns_year": "2024", "reprt_code": "11011",
       "rcept_no": "20250315000001", "account_id": "ifrs-full_Revenue", "account_nm": "매출액",
       "sj_div": "IS", "thstrm_amount": "1,000", "currency": "KRW"}


def call(client, args=ARGS):
    return client.post("/mcp", headers=HEADERS, json={"jsonrpc": "2.0", "id": 1,
        "method": "tools/call", "params": {"name": "get_financial_statements", "arguments": args}}).json()["result"]


def test_financial_contract_and_exact_source_date():
    def handler(request):
        assert request.url.params["crtfc_key"] == KEY
        if request.url.path.endswith("fnlttSinglAcntAll.json"):
            assert all(request.url.params[k] == str(v) for k, v in ARGS.items())
            return httpx.Response(200, json={"status": "000", "list": [ROW]})
        return httpx.Response(200, json={"status": "000", "total_page": 1,
            "list": [{"rcept_no": ROW["rcept_no"], "rcept_dt": "20250317"}]})
    with TestClient(create_app(settings(), transport=httpx.MockTransport(handler))) as client:
        result = call(client)
    assert not result.get("isError")
    data = result["structuredContent"]
    assert data["accounts"][0]["thstrm_amount"] == "1,000"
    assert data["sources"][0]["published_at"] == "2025-03-17"
    assert KEY not in str(data)


@pytest.mark.parametrize("payload,code", [
    ({"status": "013"}, None),
    ({"status": "010", "message": KEY}, "OPENDART_AUTH_FAILED"),
    ({"status": "000", "list": [{**ROW, "corp_code": "99999999"}]}, "OPENDART_UNAVAILABLE"),
    ({"status": "000", "list": {}}, "OPENDART_UNAVAILABLE"),
])
def test_financial_empty_and_invalid_responses(payload, code):
    with TestClient(create_app(settings(), transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))) as client:
        result = call(client)
    if code:
        assert result["isError"] and code in str(result) and KEY not in str(result)
    else:
        assert result["structuredContent"]["accounts"] == []


@pytest.mark.parametrize("field,value", [("corp_code", "bad"), ("bsns_year", 2014), ("reprt_code", "bad"), ("fs_div", "bad")])
def test_financial_invalid_input_does_not_call_provider(field, value):
    def handler(_):
        pytest.fail("invalid input reached provider")
    with TestClient(create_app(settings(), transport=httpx.MockTransport(handler))) as client:
        assert call(client, {**ARGS, field: value})["isError"]
