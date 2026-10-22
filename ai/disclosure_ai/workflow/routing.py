from langgraph.graph import END
from langgraph.types import Send


def selected(state):
    jobs = state.get("jobs", {})
    pending = [
        selection
        for selection in state.get("base", {}).get("selected", [])
        if selection["perspective_type"] not in state.get("results", {})
        and jobs.get(selection["perspective_type"], {}).get("status", "PENDING") == "PENDING"
    ]
    return [Send("perspective", {**state, "selection": item}) for item in pending] or END


def status(state):
    return (
        "KEY"
        if any(job.get("status") == "NEEDS_TOOLS" for job in state.get("jobs", {}).values())
        else "JOIN"
    )


def resume(state):
    return (
        "S2"
        if any(job["status"] == "PENDING" for job in state.get("jobs", {}).values())
        else "REPORT_AGENT"
    )
