from disclosure_ai.analysis.perspectives.service import analyze_perspective


async def perspective(run, state):
    return await analyze_perspective(
        run,
        selection=state["selection"],
        jobs=state.get("jobs", {}),
        request=state["request"],
        memo=state.get("memo", {}),
        base=state["base"],
        filing=state.get("filing", {}),
        context=state["context"],
        documents=state["documents"],
    )
