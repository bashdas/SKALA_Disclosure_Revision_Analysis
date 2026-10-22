from disclosure_ai.domain.errors import RunCancelled
from disclosure_ai.domain.policies.evidence_policy import validated_sources
from disclosure_ai.errors import LimitReached
from disclosure_ai.llm.mappings import analysis_context, perspective_result
from disclosure_ai.llm.schemas.analysis import PerspectiveAnswer


async def register(run, state):
    await run.stage(state, "PERSPECTIVE_ANALYSIS", {"selected": state["base"]["selected"]})
    return {}


async def analyze_perspective(
    run, *, selection, jobs, request, memo, base, filing, context, documents
):
    # Selection and evidence are explicit inputs, independent of graph state.
    kind = selection["perspective_type"]
    job = jobs.get(kind, {})
    observations = job.get("observations", [])
    limits = job.get("limitations", [])
    try:
        if not job and hasattr(run.tools, "perspective"):
            await run.tools.perspective(run.h.task_id, selection)
        answer = await run.h.model(
            "perspective",
            {
                "selection": selection,
                "request": request,
                "memo": memo,
                "base": base,
                "context": analysis_context(filing, context),
                "observations": observations,
            },
            PerspectiveAnswer,
        )
        result = perspective_result(answer)
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
        result["sources"] = validated_sources(result["sources"], documents, context)
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


async def perspective(run, state):
    """Compatibility entry; canonical nodes pass explicit inputs to the service."""
    return await analyze_perspective(
        run,
        selection=state["selection"],
        jobs=state.get("jobs", {}),
        request=state["request"],
        memo=state.get("memo", {}),
        base=state["base"],
        filing=state.get("filing", {}),
        context=state["context"],
        documents=state["documents"],
    )


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
