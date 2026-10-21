from datetime import datetime, timezone

from disclosure_ai.business import RunCancelled
from disclosure_ai.documents import validated_sources
from disclosure_ai.schemas import ReportText


async def join(run, state):
    warnings = list(state.get("base", {}).get("limitations", []))
    if not state["filing"].get("complete_correction_table"):
        warnings.append("정정표 전체 추출을 확인하지 못했습니다. 본문 근거를 추가 확인해야 합니다.")
    for result in state.get("results", {}).values():
        warnings.extend(result.get("limitations", []))
    return {"warnings": warnings}


async def report(run, state):
    await run.stage(state, "REPORT_GENERATION")
    context = {
        "request": state["request"],
        "base": state.get("base"),
        "results": state.get("results", {}),
        "warnings": state.get("warnings", []),
    }
    warnings = []
    try:
        report = (await run.h.model("report", context, ReportText, report=True)).model_dump()
    except RunCancelled:
        raise
    except Exception as error:
        base = state.get("base", {})
        proposals = base.get("proposals", [])
        report = {
            "summary": base.get("summary", "입력 자료 부족으로 영향 분석을 수행하지 못했습니다."),
            "correction": "\n".join(
                f"{c['label']}: 정정 전 {c['before']}, 정정 후 {c['after']}"
                for c in state.get("filing", {}).get("changes", [])
            )
            or "정정 항목을 확보하지 못했습니다.",
            "memo_impact": "\n".join(p["reason"] for p in proposals)
            or "메모 영향에 대한 수정 제안 근거를 확보하지 못했습니다.",
            "suggestions": "\n".join(p["after_text"] for p in proposals if p.get("after_text"))
            or "확정된 메모 수정문이 없습니다.",
            "perspectives": "\n".join(
                f"{kind}: {result['status']}\n{result['findings']}"
                for kind, result in state.get("results", {}).items()
            )
            or base.get("no_additional_analysis_reason")
            or "추가 관점을 수행하지 않았습니다.",
            "limitations": "모델 보고서 생성 실패: " + type(error).__name__,
        }
        warnings.append("보고서 모델 생성에 실패해 확보한 결과로 구성했습니다.")
    base = state.get("base", {})
    sources = [s for item in base.get("proposals", []) for s in item["evidence"]]
    sources += [s for item in state.get("results", {}).values() for s in item["sources"]]
    if not sources:
        sources = validated_sources(
            state.get("context", []), state.get("documents", []), state.get("context", [])
        )
    checked, check_warnings = await run.h.review_output(
        {**context, "sections": report, "sources": sources}
    )
    warnings.extend(check_warnings)
    checked["warnings"] = list(dict.fromkeys([w for w in checked["warnings"] if w] + warnings))
    base = checked.get("base") or {}
    lines = [
        "정정공시 분석 보고서",
        "기업: " + state["request"]["company_name_snapshot"],
        "접수번호: " + state["request"]["disclosure_receipt_no"],
    ]
    titles = {
        "summary": "처리 결과 요약",
        "correction": "정정 내용",
        "memo_impact": "메모 영향",
        "suggestions": "수정 제안",
        "perspectives": "관점별 분석",
        "limitations": "제한 사유",
    }
    for title, text in checked["sections"].items():
        lines.extend([titles[title], text or "검사에서 제외된 서술입니다."])
    for proposal in base.get("proposals", []):
        lines.extend(
            ["메모 수정 제안", proposal["reason"], proposal.get("after_text") or "수정문 없음"]
        )
    for result in checked["results"].values():
        lines.extend(
            [
                result["perspective_type"] + ": " + result["status"],
                result["selection_reason"] or "선택 근거는 출력 검사에서 제외했습니다.",
                result["findings"] or "분석 서술은 출력 검사에서 제외했습니다.",
            ]
        )
    reason = base.get("no_additional_analysis_reason")
    if not base.get("selected"):
        reason = reason or "추가 관점을 실행하지 않았습니다. 상세 사유는 출력할 수 없습니다."
        lines.append(reason)
    lines.append("출처")
    for source in checked["sources"]:
        lines.append(
            f"{source['document_id']} {source['location']} {source.get('url') or ''} 원문 인용: {source['quote']}"
        )
    lines.extend(checked["warnings"])
    body = {
        "content": "\n".join(lines),
        "report_json": checked,
        "has_warnings": bool(checked["warnings"]) or not bool(base),
        "no_additional_analysis_reason": reason,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    run.h.ledger.keep(run.h.task_id, "report", body)
    return {"report": body, "warnings": warnings}


async def save(run, state):
    result = await run.h.tool(
        "business_save_report",
        {"task_id": run.h.task_id, "report": state["report"]},
        run.tools.call,
        report=True,
        scope=state["scope"],
    )
    if result.get("error"):
        result = {"status": "SAVE_FAILED", "error": result["error"], "report": state["report"]}
    else:
        result["report"] = state["report"]
    run.h.ledger.keep(run.h.task_id, "result", result)
    return {"output": result}
