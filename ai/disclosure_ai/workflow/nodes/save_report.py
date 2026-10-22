from disclosure_ai.analysis.reporting.service import save_report


async def save(run, state):
    return await save_report(run, report=state["report"], scope=state["scope"])
