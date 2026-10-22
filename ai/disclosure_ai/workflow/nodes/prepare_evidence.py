from disclosure_ai.analysis.inputs.service import prepare_evidence


async def prepare(run, state):
    return await prepare_evidence(
        run,
        filing=state["filing"],
        memo=state["memo"],
        request=state["request"],
        scope=state["scope"],
    )
