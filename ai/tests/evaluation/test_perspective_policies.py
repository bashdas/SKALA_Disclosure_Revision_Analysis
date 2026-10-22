"""Deterministic policy cases; model quality still needs the live Golden Set evaluation."""

import pytest

from disclosure_ai.analysis.perspectives.registry import DEFAULT_REGISTRY, PerspectiveRegistry
from disclosure_ai.domain.models.perspective import PerspectiveDefinition
from disclosure_ai.domain.policies.proposal_policy import validate_proposals
from disclosure_ai.domain.policies.tool_permission_policy import prepare_lookup


def test_new_definition_drives_tool_policy_without_a_graph_change():
    definition = PerspectiveDefinition(
        "ACCOUNTING", "회계", "revenue recognition", frozenset({"academic"})
    )
    registry = PerspectiveRegistry((definition,))
    name, args = prepare_lookup(
        registry.get("ACCOUNTING"),
        {"tool": "academic", "query": "private memo sentence"},
        {"disclosure_receipt_no": "20260203800709"},
        task_id="task",
        rag_ready=False,
    )
    assert name == "academic"
    assert args == {"query": "revenue recognition", "as_of": "2026-02-03"}
    with pytest.raises(ValueError, match="TOOL_NOT_ALLOWED"):
        prepare_lookup(
            definition, {"tool": "financial", "query": "x"}, {}, task_id="task", rag_ready=False
        )
    with pytest.raises(ValueError, match="DUPLICATE_PERSPECTIVE"):
        registry.register(definition)


def test_rag_selection_and_financial_defaults_are_preserved():
    definition = DEFAULT_REGISTRY.get("FINANCE")
    request = {"disclosure_receipt_no": "20260203800709", "corp_code": "00126380"}
    assert prepare_lookup(
        definition,
        {"tool": "local_search", "query": "revenue"},
        request,
        task_id="task",
        rag_ready=True,
    ) == (
        "search_evidence",
        {"query": "revenue", "task_id": "task", "top_k": 5},
    )
    _, args = prepare_lookup(
        definition,
        {"tool": "financial", "query": "revenue"},
        request,
        task_id="task",
        rag_ready=False,
    )
    assert args["bsns_year"] == 2025 and args["fs_div"] == "CFS"


@pytest.mark.parametrize("before", ["", "메모에 없는 문장"])
def test_unsupported_memo_proposals_are_held_without_an_llm(before):
    proposal = {
        "before_text": before,
        "after_text": "unsupported",
        "impact_type": "FACT_UPDATE",
        "evidence": [],
        "reason": "unsupported",
    }
    warnings = validate_proposals([proposal], "원래 메모", [], [])
    assert proposal["impact_type"] == "HOLD"
    assert proposal["after_text"] is None and proposal["evidence"] == []
    assert warnings
