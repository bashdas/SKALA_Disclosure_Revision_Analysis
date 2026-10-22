import asyncio

from disclosure_ai.analysis.impact.service import impact as impact
from disclosure_ai.domain.policies.document_search import search_documents
from disclosure_ai.domain.policies.evidence_policy import validated_sources


async def collect_inputs(run, *, request, scope):
    await run.stage({}, "INPUT_COLLECTION")
    req = request
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
            scope=scope,
        ),
        run.h.tool("business_get_memo", access, run.tools.call, scope=scope),
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


async def collect(run, state):
    """Compatibility entry; canonical nodes pass explicit inputs to the service."""
    return await collect_inputs(run, request=state["request"], scope=state["scope"])


async def prepare_evidence(run, *, filing, memo, request, scope):
    await run.stage({}, "RAG_PREPARATION")
    documents = filing["documents"] + [memo]
    context = list(filing.get("changes", []))
    context += search_documents(
        documents,
        request["company_name_snapshot"]
        + " 계약 정정 금액 매출 기간 위험 earnings revenue profit EPS goodwill impairment forecast guidance",
        limit=12,
    )
    # 원문을 보존하고 모델에는 고정 버전의 메모와 정정표를 우선 전달합니다.
    context.append(
        {
            "document_id": memo["document_id"],
            "location": "memo",
            "quote": memo["text"],
        }
    )
    index = await run.h.tool(
        "ensure_analysis_index",
        {"task_id": run.h.task_id},
        run.tools.call,
        scope=scope,
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
            scope=scope,
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


async def prepare(run, state):
    """Compatibility entry; canonical nodes pass explicit inputs to the service."""
    return await prepare_evidence(
        run,
        filing=state["filing"],
        memo=state["memo"],
        request=state["request"],
        scope=state["scope"],
    )
