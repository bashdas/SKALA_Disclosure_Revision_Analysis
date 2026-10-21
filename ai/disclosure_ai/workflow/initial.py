import asyncio

from disclosure_ai.schemas import BaseAnalysis
from disclosure_ai.services.business import RunCancelled
from disclosure_ai.services.documents import search_documents, typo_only, validated_sources


async def collect(run, state):
    await run.stage(state, "INPUT_COLLECTION")
    req = state["request"]
    access = {
        "task_id": run.h.task_id,
        "memo_id": req["memo_id"],
        "version": req["base_memo_version"],
    }
    filing, memo = await asyncio.gather(
        run.h.tool(
            "disclosure_get_document",
            {**access, "receipt_no": req["disclosure_receipt_no"]},
            run.tools.call,
            scope=state["scope"],
        ),
        run.h.tool("business_get_memo", access, run.tools.call, scope=state["scope"]),
    )
    warnings = []
    if filing.get("error") or not filing.get("documents"):
        warnings.append(
            "공시 조회 또는 원문 처리 실패: " + str(filing.get("error", "EMPTY_DOCUMENT"))
        )
    if memo.get("error") or not memo.get("text") or memo.get("version") != req["base_memo_version"]:
        warnings.append(
            "메모 조회 또는 고정 버전 확인 실패: " + str(memo.get("error", "VERSION_MISMATCH"))
        )
    request = dict(req)
    if filing.get("corp_code"):
        if req.get("corp_code") and req["corp_code"] != filing["corp_code"]:
            warnings.append("공시의 기업코드가 고정 입력과 일치하지 않습니다.")
        else:
            request["corp_code"] = filing["corp_code"]
    if req["company_name_snapshot"] == "기업명 미확정" and filing.get("company_name"):
        request["company_name_snapshot"] = filing["company_name"]
    return {"request": request, "filing": filing, "memo": memo, "warnings": warnings}


async def prepare(run, state):
    await run.stage(state, "RAG_PREPARATION")
    documents = state["filing"]["documents"] + [state["memo"]]
    context = list(state["filing"].get("changes", []))
    context += search_documents(
        documents, state["request"]["company_name_snapshot"] + " 계약 정정 금액 매출 기간 위험"
    )
    # 원문을 보존하고 모델에는 고정 버전의 메모와 정정표를 우선 전달합니다.
    context.append(
        {
            "document_id": state["memo"]["document_id"],
            "location": "memo",
            "quote": state["memo"]["text"],
        }
    )
    index = await run.h.tool(
        "ensure_analysis_index",
        {"task_id": run.h.task_id},
        run.tools.call,
        scope=state["scope"],
    )
    warnings = []
    ready = index.get("indexed") is True
    if ready:
        found = await run.h.tool(
            "search_evidence",
            {
                "task_id": run.h.task_id,
                "query": "정정 내용과 기존 메모의 계약 금액, 기간 및 위험",
                "top_k": 5,
            },
            run.tools.call,
            scope=state["scope"],
        )
        documents.extend(found.get("documents", []))
        context.extend(found.get("sources", []))
        if found.get("error"):
            warnings.append("RAG 검색 미완료: " + found["error"])
    else:
        warnings.append("RAG 색인 미완료: " + str(index.get("error", "INDEX_NOT_READY")))
    return {
        "documents": documents,
        "context": context,
        "rag_ready": ready,
        "warnings": warnings,
    }


async def impact(run, state):
    await run.stage(state, "BASE_ANALYSIS")
    if typo_only(state["filing"]):
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
            "base", {"request": state["request"], "context": state["context"]}, BaseAnalysis
        )
        data = base.model_dump()
        seen = set()
        data["selected"] = [
            s
            for s in data["selected"]
            if not (s["perspective_type"] in seen or seen.add(s["perspective_type"]))
        ]
        for proposal in data["proposals"]:
            proposal["evidence"] = validated_sources(
                proposal["evidence"], state["documents"], state["context"]
            )
            if proposal["before_text"] not in state["memo"]["text"] or not proposal["evidence"]:
                proposal["impact_type"] = "HOLD"
                proposal["after_text"] = None
                data["limitations"].append(
                    "메모 문장 또는 출처를 확인하지 못한 제안은 보류했습니다."
                )
        if not data["selected"] and not data["no_additional_analysis_reason"]:
            data["no_additional_analysis_reason"] = "기본 분석에서 추가 관점을 선택하지 않았습니다."
        return {"base": data}
    except RunCancelled:
        raise
    except Exception as error:
        return {"warnings": ["기본 분석 미수행: " + type(error).__name__]}
