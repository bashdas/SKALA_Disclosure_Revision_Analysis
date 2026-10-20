import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as client:
        yield client


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "rag-mcp"}


def test_mcp_initialize_and_tools(client):
    headers = {"Accept": "application/json, text/event-stream", "Host": "localhost:8082"}
    response = client.post("/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                   "clientInfo": {"name": "smoke-test", "version": "1.0"}},
    })
    assert response.status_code == 200
    assert "serverInfo" in response.json()["result"]
    response = client.post("/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
    })
    assert response.status_code == 200
    assert {t["name"] for t in response.json()["result"]["tools"]} == {"ensure_analysis_index", "search_evidence"}
