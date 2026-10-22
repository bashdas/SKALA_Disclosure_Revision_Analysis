import asyncio

from disclosure_ai.schemas import BaseAnalysis
from disclosure_ai.services.business import RunCancelled
from disclosure_ai.services.documents import (
    disclosure_type,
    model_context,
    reference_frames,
    search_documents,
    validated_sources,
)


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
    kind = disclosure_type(filing, req.get("disclosure_type", "UNKNOWN"))
    request["disclosure_type"] = kind
    filing = {**filing, "analysis_type": kind}
    if kind == "UNKNOWN":
        filing["analysis_type_reason"] = (
            "등록 메타데이터와 공식 공시 제목의 유형이 서로 다릅니다."
            if req.get("disclosure_type") in {"NEW", "CORRECTION"}
            and disclosure_type(filing) in {"NEW", "CORRECTION"}
            else "등록 메타데이터 또는 공식 제목에서 공시 유형을 확인할 정보가 부족합니다."
        )
    if kind != "CORRECTION":
        filing = {**filing, "changes": [], "complete_correction_table": False}
    return {"request": request, "filing": filing, "memo": memo, "warnings": warnings}


async def prepare(run, state):
    await run.stage(state, "RAG_PREPARATION")
    documents = state["filing"]["documents"] + [state["memo"]]
    context = list(state["filing"].get("changes", []))
    if state["filing"].get("analysis_type") != "CORRECTION" or not context:
        # 검색 점수가 낮은 일정 안내도 실제 공시 원문이 모델 입력에 남도록 합니다.
        context.extend(
            {"document_id": doc["document_id"], "location": "line:1:overview",
             "quote": doc["text"][:2500], "url": doc.get("url"),
             "published_at": doc.get("published_at")}
            for doc in state["filing"]["documents"] if doc.get("text", "").strip()
        )
    context += search_documents(
        documents,
        state["request"]["company_name_snapshot"]
        + " " + (state["filing"].get("report_name") or ""),
        limit=12,
    )
    context.extend(reference_frames(state["filing"], state["memo"])["applied_valuation_rows"])
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
                "query": ("정정 내용과 기존 메모의 계약 금액, 기간 및 위험"
                          if state["filing"].get("analysis_type") == "CORRECTION"
                          else "공시 사실과 기존 메모의 수치, 전망 및 가정"),
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
        "context": list(
            {
                (source["document_id"], source["location"], source["quote"]): source
                for source in validated_sources(context, documents, context)
            }.values()
        ),
        "rag_ready": ready,
        "warnings": warnings,
    }


async def impact(run, state):
    await run.stage(state, "BASE_ANALYSIS")
    kind = state["filing"].get("analysis_type", "UNKNOWN")
    try:
        base = await run.h.model(
            "base",
            {
                "request": state["request"],
                "analysis_type": kind,
                **model_context(state["filing"], state["context"], state["memo"]),
            },
            BaseAnalysis,
        )
        data = base.model_dump()
        if kind == "UNKNOWN":
            data["limitations"].append(
                "공시 유형을 확정하지 못했습니다. "
                + state["filing"].get("analysis_type_reason", "유형을 확인할 메타데이터가 부족합니다.")
                + " 정정 전후 비교는 보류했습니다."
            )
        elif kind == "CORRECTION" and not state["filing"].get("complete_correction_table"):
            data["limitations"].append("정정공시의 정정표 전체를 확인하지 못했습니다. 확인한 본문 범위에서 검토했습니다.")
        seen = set()
        data["selected"] = [
            s
            for s in data["selected"]
            if not (s["perspective_type"] in seen or seen.add(s["perspective_type"]))
        ]
        for proposal in data["proposals"]:
            if proposal["impact_type"] == "CALCULATION_UPDATE" and (
                not proposal.get("calculation_basis")
                or proposal["calculation_basis"] not in state["memo"]["text"]
            ):
                proposal["impact_type"] = "INTERPRETATION_REVIEW"
                proposal["after_text"] = None
                proposal["reason"] = (
                    "기존 계산식과 잔여 매출 반영액을 확인하지 못해 해석 재검토로 분류했습니다. "
                    "금액 수정은 보류합니다."
                )
            proposal["evidence"] = validated_sources(
                proposal["evidence"], state["documents"], state["context"]
            )
            if (
                not proposal["before_text"].strip()
                or proposal["before_text"] not in state["memo"]["text"]
                or not proposal["evidence"]
                or proposal["impact_type"] == "HOLD"
            ):
                proposal["impact_type"] = "HOLD"
                proposal["after_text"] = None
                proposal["before_text"] = ""
                proposal["reason"] = "메모 문장 또는 출처를 확인하지 못해 작성하지 않았습니다."
                proposal["evidence"] = []
                data["limitations"].append(
                    "메모 문장 또는 출처를 확인하지 못한 제안은 보류했습니다."
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
