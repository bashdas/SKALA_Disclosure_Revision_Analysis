import hashlib
from uuid import UUID

from fastapi.testclient import TestClient

from disclosure_ai import api
from disclosure_ai.schemas import AnalysisRequest


def request():
    return AnalysisRequest(
        analysis_task_id="00000000-0000-0000-0000-000000000001",
        memo_id="00000000-0000-0000-0000-000000000002",
        base_memo_version=1,
        disclosure_receipt_no="20261020000001",
        company_name_snapshot="테스트기업",
        thread_id="thread",
    )


def test_result_scope_and_internal_auth(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_STATE_PATH", str(tmp_path / "state.sqlite"))
    monkeypatch.setenv("AI_INTERNAL_TOKEN", "test-internal-token-32-characters-long")

    async def authorized(body, authorization):
        return None, {"scope": str(body.memo_id)}

    monkeypatch.setattr(api, "authorized", authorized)
    body = request()
    with TestClient(api.app) as client:

        async def seed():
            api.app.state.ledger.begin(
                str(body.analysis_task_id),
                hashlib.sha256(body.model_dump_json().encode()).hexdigest(),
            )
            api.app.state.ledger.keep(
                str(body.analysis_task_id),
                "result",
                {"status": "SAVE_FAILED", "report": "private report"},
            )

        client.portal.call(seed)
        path = f"/internal/analyses/{body.analysis_task_id}/result"
        assert (
            client.post(
                path, json=body.model_dump(mode="json"), headers={"Authorization": "Bearer test"}
            ).status_code
            == 403
        )
        headers = {
            "Authorization": "Bearer test",
            "X-AI-Token": "test-internal-token-32-characters-long",
        }
        assert (
            client.post(path, json=body.model_dump(mode="json"), headers=headers).json()["result"][
                "report"
            ]
            == "private report"
        )
        wrong = body.model_copy(update={"memo_id": UUID("00000000-0000-0000-0000-000000000003")})
        assert (
            client.post(path, json=wrong.model_dump(mode="json"), headers=headers).status_code
            == 409
        )


def test_api_resume_uses_original_deadline(monkeypatch, tmp_path):
    import asyncio
    import json
    import time
    from types import SimpleNamespace

    monkeypatch.setenv("AI_STATE_PATH", str(tmp_path / "state.sqlite"))
    body = request()
    task_id = str(body.analysis_task_id)

    class WaitingGraph:
        async def aget_state(self, config):
            return SimpleNamespace(next=("S3",))

        async def ainvoke(self, initial, config):
            assert initial is None
            await asyncio.Event().wait()

    async def internal(*args, **kwargs):
        return {}

    monkeypatch.setattr(api, "internal_request", internal)
    monkeypatch.setattr(api, "AnalysisGraph", lambda *args: SimpleNamespace(graph=WaitingGraph()))
    with TestClient(api.app) as client:

        async def check():
            ledger = api.app.state.ledger
            ledger.begin(task_id, "resume")
            ledger.db.execute(
                "UPDATE runs SET started=? WHERE id=?", (time.time() - 119.99, task_id)
            )
            ledger.db.commit()
            await asyncio.wait_for(api.run(body, object(), {"scope": "org"}), 0.5)
            result = json.loads(ledger.row(task_id)["result"])
            assert result["status"] == "FAILED"
            assert result["error"] == "TimeoutError"

        client.portal.call(check)
