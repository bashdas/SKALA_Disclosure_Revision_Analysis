from disclosure_ai.domain.errors import RunCancelled
from disclosure_ai.domain.policies.perspective_selection_policy import unique_selections
from disclosure_ai.domain.policies.proposal_policy import validate_proposals
from disclosure_ai.domain.policies.typo_policy import typo_only
from disclosure_ai.llm.mappings import analysis_context, base_result
from disclosure_ai.llm.schemas.analysis import BaseAnalysis


async def analyze_impact(run, *, filing, memo, request, context, documents):
    await run.stage({}, "BASE_ANALYSIS")
    if typo_only(filing):
        return {
            "base": {
                "summary": "공백 차이만 확인했습니다. 영향 분석은 미수행했습니다.",
                "proposals": [],
                "selected": [],
                "no_additional_analysis_reason": "허용된 공백 차이만 확인해 모델 영향 분석을 생략했습니다.",
                "limitations": [],
            }
        }
    try:
        base = await run.h.model(
            "base",
            {
                "request": request,
                "memo": memo,
                "context": analysis_context(filing, context),
            },
            BaseAnalysis,
        )
        data = base_result(base)
        data["selected"] = unique_selections(data["selected"])
        data["limitations"].extend(
            validate_proposals(data["proposals"], memo["text"], documents, context)
        )
        # 출처가 연결되지 않은 기본 요약을 관점 분석에 재사용하지 않습니다.
        data["summary"] = ""
        data["limitations"] = list(dict.fromkeys(data["limitations"]))
        if not data["selected"] and not data["no_additional_analysis_reason"]:
            data["no_additional_analysis_reason"] = "기본 분석에서 추가 관점을 선택하지 않았습니다."
        return {"base": data}
    except RunCancelled:
        raise
    except Exception as error:
        return {"warnings": ["기본 분석 미수행: " + type(error).__name__]}


async def impact(run, state):
    """Compatibility entry; canonical nodes pass explicit inputs to the service."""
    return await analyze_impact(
        run,
        filing=state["filing"],
        memo=state["memo"],
        request=state["request"],
        context=state["context"],
        documents=state["documents"],
    )
