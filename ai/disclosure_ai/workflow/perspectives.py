from langgraph.graph import END
from langgraph.types import Send

from disclosure_ai.errors import LimitReached
from disclosure_ai.schemas import PerspectiveAnswer
from disclosure_ai.services.business import RunCancelled
from disclosure_ai.services.documents import analysis_context, validated_sources


def selected(state):
    jobs = state.get("jobs", {})
    pending = [
        selection
        for selection in state.get("base", {}).get("selected", [])
        if selection["perspective_type"] not in state.get("results", {})
        and jobs.get(selection["perspective_type"], {}).get("status", "PENDING") == "PENDING"
    ]
    return [Send("perspective", {**state, "selection": item}) for item in pending] or END


async def register(run, state):
    await run.stage(state, "PERSPECTIVE_ANALYSIS", {"selected": state["base"]["selected"]})
    return {}


async def perspective(run, state):
    selection = state["selection"]
    kind = selection["perspective_type"]
    job = state.get("jobs", {}).get(kind, {})
    observations = job.get("observations", [])
    limits = job.get("limitations", [])
    try:
        if not job and hasattr(run.tools, "perspective"):
            await run.tools.perspective(run.h.task_id, selection)
        answer = await run.h.model(
            "perspective",
            {
                "selection": selection,
                "request": state["request"],
                "memo": state.get("memo", {}),
                "base": state["base"],
                "context": analysis_context(state.get("filing", {}), state["context"]),
                "observations": observations,
            },
            PerspectiveAnswer,
        )
        result = answer.model_dump()
        if result["status"] == "NEEDS_TOOLS" and result["requests"]:
            return {
                "jobs": {
                    kind: {
                        **job,
                        "selection": selection,
                        "status": "NEEDS_TOOLS",
                        "requests": result["requests"],
                        "observations": observations,
                        "limitations": list(dict.fromkeys(limits + result["limitations"])),
                    }
                }
            }
        result["sources"] = validated_sources(
            result["sources"], state["documents"], state["context"]
        )
        if not result["sources"]:
            result["status"] = "INSUFFICIENT_EVIDENCE"
            limits = [*limits, "검증 가능한 출처가 없습니다."]
    except RunCancelled:
        raise
    except Exception as error:
        result = {
            "status": "LIMIT_REACHED" if isinstance(error, LimitReached) else "FAILED",
            "findings": "추가 분석을 완료하지 못했습니다.",
            "sources": [],
            "limitations": [type(error).__name__],
        }
    result["limitations"] = list(dict.fromkeys(result["limitations"] + limits))
    return await finish_perspective(run, kind, selection, result)


async def finish_perspective(run, kind, selection, result):
    # 근거 부족 서술은 후속 모델과 업무 DB의 관점 결과에도 남기지 않습니다.
    if result["status"] != "COMPLETED":
        result = {**result, "findings": "", "sources": [], "requests": []}
    warnings = []
    if hasattr(run.tools, "perspective"):
        try:
            await run.tools.perspective(run.h.task_id, selection, result)
        except RunCancelled:
            raise
        except Exception as error:
            warnings.append("관점 상태 전달 실패: " + type(error).__name__)
    return {
        "results": {kind: {**selection, **result}},
        "jobs": {kind: {"status": result["status"], "selection": selection}},
        "warnings": warnings,
    }
