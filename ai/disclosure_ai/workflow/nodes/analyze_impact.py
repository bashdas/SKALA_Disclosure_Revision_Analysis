from disclosure_ai.analysis.impact.service import analyze_impact


async def impact(run, state):
    return await analyze_impact(
        run,
        filing=state["filing"],
        memo=state["memo"],
        request=state["request"],
        context=state["context"],
        documents=state["documents"],
    )
