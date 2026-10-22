from disclosure_ai.analysis.evidence.service import requests as analyze


async def requests(run, state):
    return await analyze(run, state)
