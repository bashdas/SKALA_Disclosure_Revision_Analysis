from disclosure_ai.analysis.inputs.service import collect_inputs


async def collect(run, state):
    return await collect_inputs(run, request=state["request"], scope=state["scope"])
