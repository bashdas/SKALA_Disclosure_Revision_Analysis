from disclosure_ai.analysis.perspectives.service import register as analyze


async def register(run, state):
    return await analyze(run, state)
