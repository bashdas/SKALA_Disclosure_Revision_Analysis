import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.client import BusinessAPIClient
from app.config import Settings
from app.main import create_app

KEY = "test-only-internal-mcp-key-not-for-production-12345"
TASK, PERSPECTIVE = str(uuid4()), str(uuid4())
HEADERS = {"Accept": "application/json, text/event-stream", "Host": "localhost:8081"}
NAMES = {"get_analysis_context", "get_analysis_status", "report_analysis_event", "update_analysis_state", "register_perspective", "update_perspective", "save_analysis_report"}


def settings():
    return Settings(_env_file=None, internal_api_key=KEY, business_api_base_url="http://business-api:8080", business_mcp_request_timeout_seconds=0.5)


def rpc(client, name, args):
    response = client.post("/mcp", headers=HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})
    assert response.status_code == 200
    return response.json()["result"]


def test_exact_seven_tools_and_no_key_argument():
    with TestClient(create_app(settings())) as client:
        response = client.post("/mcp", headers=HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        tools = response.json()["result"]["tools"]
        assert {item["name"] for item in tools} == NAMES
        assert all("internal_api_key" not in item["inputSchema"]["properties"] for item in tools)
        assert KEY not in response.text
        assert client.get("/health").status_code == 200


@pytest.mark.parametrize("name,args,method,suffix", [
    ("get_analysis_context", {}, "GET", "context"),
    ("get_analysis_status", {}, "GET", "status"),
    ("report_analysis_event", {"event_type": "BASE_ANALYSIS_STARTED", "payload": {"message": "summary"}}, "POST", "events"),
    ("update_analysis_state", {"status": "RUNNING", "stage": "INPUT_COLLECTION", "has_warnings": False}, "POST", "state"),
    ("register_perspective", {"perspective_type": "FINANCE", "selection_reason": "Impact", "question": "Check", "max_tool_calls": 5, "timeout_seconds": 120}, "POST", "perspectives"),
    ("update_perspective", {"perspective_id": PERSPECTIVE, "status": "COMPLETED", "result": {}}, "PATCH", "perspectives/" + PERSPECTIVE),
    ("save_analysis_report", {"content": "Report", "report": {"claims": []}, "has_warnings": True, "no_additional_analysis_reason": "Base sufficient"}, "POST", "report"),
])
def test_tool_http_contract(name, args, method, suffix):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == method
        assert str(request.url) == f"http://business-api:8080/internal/analyses/{TASK}/{suffix}"
        assert request.headers["X-Internal-API-Key"] == KEY and "authorization" not in request.headers
        assert request.extensions["timeout"]["read"] == 0.5
        expected = {key: value for key, value in args.items() if key != "perspective_id"}
        assert (json.loads(request.content) if request.content else {}) == expected
        return httpx.Response(200, json={"task_id": TASK, "status": "RUNNING"})

    with TestClient(create_app(settings(), transport=httpx.MockTransport(handler))) as client:
        result = rpc(client, name, {"task_id": TASK, **args})
        assert not result.get("isError", False)
        assert result["structuredContent"] == {"task_id": TASK, "status": "RUNNING"}
        assert len(calls) == 1


@pytest.mark.parametrize("status,code,message", [(404, "ANALYSIS_NOT_FOUND", "Analysis not found"), (409, "INVALID_ANALYSIS_STATE", "Transition not allowed"), (503, "REPORT_SAVE_FAILED", "Report save failed; retry the same payload")])
def test_safe_api_errors(status, code, message):
    transport = httpx.MockTransport(lambda _: httpx.Response(status, json={"error": {"code": code, "message": message}}))
    with TestClient(create_app(settings(), transport=transport)) as client:
        result = rpc(client, "get_analysis_status", {"task_id": TASK})
        assert result["isError"]
        text = result["content"][0]["text"]
        assert code in text and message in text and str(status) in text
        assert ("business_api_4xx" if status < 500 else "business_api_5xx") in text


@pytest.mark.parametrize("error,code", [(httpx.ReadTimeout, "BUSINESS_API_TIMEOUT"), (httpx.ConnectError, "BUSINESS_API_CONNECTION_FAILED")])
def test_transport_failures_redact_details(error, code, caplog):
    def handler(request):
        raise error("private diagnostic " + KEY, request=request)

    with TestClient(create_app(settings(), transport=httpx.MockTransport(handler))) as client:
        result = rpc(client, "get_analysis_context", {"task_id": TASK})
        assert result["isError"] and code in str(result)
        assert KEY not in str(result) and "private diagnostic" not in str(result)
    assert KEY not in caplog.text


@pytest.mark.parametrize("status,body", [(200, "not-json"), (200, "[]"), (200, "null"), (302, "")])
def test_malformed_response(status, body):
    with TestClient(create_app(settings(), transport=httpx.MockTransport(lambda _: httpx.Response(status, text=body)))) as client:
        result = rpc(client, "get_analysis_context", {"task_id": TASK})
        assert result["isError"] and "BUSINESS_API_INVALID_RESPONSE" in str(result)


def test_client_reuse_and_shutdown():
    async def run():
        adapter = BusinessAPIClient(settings(), transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"ok": True})))
        async with adapter:
            http = adapter._http
            await adapter.request("GET", "/internal/analyses/test/status")
            await adapter.request("GET", "/internal/analyses/test/status")
            assert adapter._http is http and not http.is_closed
        assert http.is_closed and adapter._http is None
    asyncio.run(run())


def test_secret_redacted_on_upstream_echo(caplog):
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"content": "text " + KEY, "X-Internal-API-Key": KEY}))
    with TestClient(create_app(settings(), transport=transport)) as client:
        result = rpc(client, "get_analysis_context", {"task_id": TASK})
        assert KEY not in str(result) and "[REDACTED]" in str(result)
    assert KEY not in caplog.text


def test_unsafe_upstream_error_has_safe_fallback():
    transport = httpx.MockTransport(lambda _: httpx.Response(500, json={"error": {"code": "UPSTREAM_FAILURE", "message": "Traceback " + KEY}}))
    with TestClient(create_app(settings(), transport=transport)) as client:
        result = rpc(client, "get_analysis_status", {"task_id": TASK})
        assert "UPSTREAM_FAILURE" in str(result) and KEY not in str(result) and "Traceback" not in str(result)


def test_missing_key_never_calls_upstream():
    def handler(_):
        pytest.fail("Unconfigured key must not be sent")
    with TestClient(create_app(Settings(_env_file=None, internal_api_key=""), transport=httpx.MockTransport(handler))) as client:
        assert client.get("/health").status_code == 200
        result = rpc(client, "get_analysis_context", {"task_id": TASK})
        assert result["isError"] and "BUSINESS_API_CONFIGURATION_ERROR" in str(result)
