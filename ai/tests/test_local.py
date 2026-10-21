import asyncio
import io
import json
import zipfile
from uuid import uuid4

import pytest
from test_analysis import fake_model

from disclosure_ai.entrypoints.local import Snapshot, analyze


def test_local_graph_preserves_snapshot_and_reuses_report(tmp_path):
    snapshot = Snapshot.model_validate(
        {
            "request": {
                "analysis_task_id": str(uuid4()),
                "memo_id": str(uuid4()),
                "base_memo_version": 1,
                "disclosure_receipt_no": "20261020000001",
                "company_name_snapshot": "테스트기업",
                "thread_id": "local",
            },
            "memo_text": "계약금액은 100입니다.",
        }
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "filing.xml",
            "<html><table><tr><th>항목</th><th>정정전</th><th>정정후</th></tr><tr><td>금액</td><td>100</td><td>80</td></tr></table></html>",
        )
    calls = []

    async def model(role, context, schema):
        calls.append(role)
        return await fake_model(role, context, schema)

    async def check():
        original = snapshot.model_dump_json()
        state = tmp_path / "state.sqlite"
        first = await analyze(snapshot, state, buffer.getvalue(), model)
        assert first["status"] == "LOCAL_SAVED"
        assert first["business_save_status"] == "PENDING_BACKEND"
        assert first["report"]["content"]
        assert snapshot.model_dump_json() == original
        assert await analyze(snapshot, state, buffer.getvalue(), model) == first
        assert calls == ["base", "report", "output_check"]
        changed = Snapshot.model_validate(json.loads(original))
        changed.memo_text = "다른 메모"
        with pytest.raises(ValueError):
            await analyze(changed, state, buffer.getvalue(), model)

    asyncio.run(check())
