from disclosure_ai.analysis.evidence.service import publish as analyze


async def publish(run, state):
    return await analyze(run, state)
