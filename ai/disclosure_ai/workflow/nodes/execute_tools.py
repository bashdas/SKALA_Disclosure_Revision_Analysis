from disclosure_ai.analysis.evidence.service import lookup as analyze


async def lookup(run, state):
    return await analyze(run, state)
