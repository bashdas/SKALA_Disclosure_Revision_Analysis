import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from disclosure_ai.infrastructure.openai.openai_model_adapter import OpenAIModelAdapter
from disclosure_ai.infrastructure.persistence.sqlite_run_repository import Ledger
from disclosure_ai.llm.schemas.analysis import BaseAnalysis
from disclosure_ai.ports.model_gateway import ModelResponse, ModelTransportError
from disclosure_ai.runtime.harness import Harness


@pytest.mark.parametrize("retryable, expected_calls", [(True, 2), (False, 1)])
def test_provider_independent_gateway_obeys_runtime_budget(tmp_path, retryable, expected_calls):
    answer = BaseAnalysis(
        summary="", proposals=[], selected=[], no_additional_analysis_reason="없음", limitations=[]
    )
    gateway = SimpleNamespace(
        parse=AsyncMock(side_effect=[ModelTransportError(retryable), ModelResponse(answer, 25)]),
        close=AsyncMock(),
    )
    ledger = Ledger(str(tmp_path / "run.sqlite"))
    ledger.begin("task", "fingerprint")

    async def check():
        harness = Harness("task", ledger, model_gateway=gateway)
        try:
            if retryable:
                assert await harness.model("base", {}, BaseAnalysis) == answer
            else:
                with pytest.raises(ModelTransportError):
                    await harness.model("base", {}, BaseAnalysis)
            assert gateway.parse.await_count == expected_calls
            assert ledger.row("task")["turns"] == expected_calls
        finally:
            await harness.close()
        gateway.close.assert_awaited_once()

    try:
        asyncio.run(check())
    finally:
        ledger.db.close()


def test_openai_adapter_maps_usage_without_exposing_sdk_response():
    answer = BaseAnalysis(
        summary="", proposals=[], selected=[], no_additional_analysis_reason="없음", limitations=[]
    )
    parse = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=answer))],
            usage=SimpleNamespace(total_tokens=42),
        )
    )
    adapter = OpenAIModelAdapter(
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse)))
    )
    result = asyncio.run(adapter.parse([], BaseAnalysis, 100))
    assert result == ModelResponse(answer, 42)
