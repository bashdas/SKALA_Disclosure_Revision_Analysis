from disclosure_ai.analysis.reporting.service import generate_report


async def report(run, state):
    return await generate_report(
        run,
        request=state["request"],
        base=state.get("base"),
        documents=state.get("documents", []),
        context=state.get("context", []),
        perspective_results=state.get("results", {}),
        filing=state.get("filing", {}),
        memo=state.get("memo", {}),
        stage_failed=state.get("stage_failed", False),
    )
