import asyncio
from types import SimpleNamespace

from disclosure_ai.workflow.initial import prepare


def test_english_earnings_evidence_reaches_base_analysis():
    async def stage(*args):
        pass

    async def tool(*args, **kwargs):
        return {"indexed": False, "error": "test"}

    run = SimpleNamespace(
        stage=stage, h=SimpleNamespace(tool=tool, task_id="test"), tools=SimpleNamespace(call=tool)
    )
    text = "\n".join(
        ["CENTENE CORP corporate statement"] * 20
        + [
            "$6.7 billion non-cash goodwill impairment",
            "Adjusted EPS forecast increases from $1.75 to $2.00",
        ]
    )
    state = {
        "request": {"company_name_snapshot": "CENTENE CORP"},
        "scope": "test",
        "filing": {"documents": [{"document_id": "sec", "text": text}]},
        "memo": {"document_id": "memo", "text": "영업권과 EPS 전망을 확인합니다."},
    }
    result = asyncio.run(prepare(run, state))
    quotes = [s["quote"] for s in result["context"] if s["document_id"] == "sec"]
    assert any("6.7 billion" in q for q in quotes)
    assert any("$1.75 to $2.00" in q for q in quotes)
