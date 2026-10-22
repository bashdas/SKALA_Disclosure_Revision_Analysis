from disclosure_ai.analysis.reporting.service import join as analyze


async def join(run, state):
    return await analyze(run, state)
