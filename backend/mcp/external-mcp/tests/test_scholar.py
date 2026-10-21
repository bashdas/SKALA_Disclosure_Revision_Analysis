import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.scholar import GoogleScholarClient, ScholarError


def config():
    return Settings(_env_file=None, serpapi_api_key="test-only-scholar-key")


def search(handler):
    async def run():
        async with GoogleScholarClient(config(), transport=httpx.MockTransport(handler)) as client:
            return await client.search("환율 위험", 1)
    return asyncio.run(run())


def test_search_metadata_and_key():
    def handler(request):
        assert request.url.params["engine"] == "google_scholar"
        assert request.url.params["api_key"] == "test-only-scholar-key"
        return httpx.Response(200, json={"organic_results": [{"result_id": "paper-1", "title": "환위험 연구",
            "link": "https://example.org/paper", "snippet": "검색 요약",
            "publication_info": {"summary": "A - Journal, 2024", "authors": [{"name": "A"}]}}]})
    result = search(handler)
    assert result["results"][0]["authors"] == ["A"]
    assert result["results"][0]["source"]["published_at"] is None
    assert "test-only-scholar-key" not in str(result)


def test_empty_results():
    assert search(lambda _: httpx.Response(200, json={"organic_results": []}))["results"] == []


@pytest.mark.parametrize("status,code", [(401,"SCHOLAR_AUTH_FAILED"), (429,"SCHOLAR_RATE_LIMITED"), (503,"SCHOLAR_UNAVAILABLE")])
def test_http_error(status, code):
    with pytest.raises(ScholarError) as error:
        search(lambda _: httpx.Response(status))
    assert error.value.code == code


@pytest.mark.parametrize("exception,code", [(httpx.ReadTimeout,"SCHOLAR_TIMEOUT"), (httpx.ConnectError,"SCHOLAR_UNAVAILABLE")])
def test_transport_error(exception, code):
    def handler(request):
        raise exception("hidden", request=request)
    with pytest.raises(ScholarError) as error:
        search(handler)
    assert error.value.code == code


def test_malformed_response():
    with pytest.raises(ScholarError) as error:
        search(lambda _: httpx.Response(200, json={"unexpected": True}))
    assert error.value.code == "SCHOLAR_INVALID_RESPONSE"


def test_scholar_mcp_tool():
    with TestClient(create_app(config(), transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"organic_results": []})))) as client:
        response = client.post("/mcp", headers={"Accept":"application/json, text/event-stream", "Host":"localhost:8083"},
            json={"jsonrpc":"2.0", "id":1, "method":"tools/call", "params":{"name":"search_academic_papers", "arguments":{"query":"hedging"}}})
        assert response.status_code == 200
        assert not response.json()["result"].get("isError")
        assert response.json()["result"]["structuredContent"]["results"] == []
