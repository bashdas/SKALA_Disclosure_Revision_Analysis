from disclosure_ai.analysis.perspectives.service import finish_perspective
from disclosure_ai.analysis.reporting.renderer import compose, source_key
from disclosure_ai.domain.errors import RunCancelled
from disclosure_ai.domain.policies.evidence_policy import validated_sources
from disclosure_ai.llm.schemas.analysis import ReportSummary


async def join(run, state):
    warnings = list(state.get("base", {}).get("limitations", []))
    if state.get("filing", {}).get("changes") and not state.get("filing", {}).get(
        "complete_correction_table"
    ):
        warnings.append("정정표 전체 추출을 확인하지 못했습니다. 본문 근거를 추가 확인해야 합니다.")
    for result in state.get("results", {}).values():
        warnings.extend(result.get("limitations", []))
    updates = {"warnings": warnings, "results": {}, "jobs": {}}
    if state.get("stage_failed"):
        for selection in state.get("base", {}).get("selected", []):
            kind = selection["perspective_type"]
            if kind in state.get("results", {}):
                continue
            completed = await finish_perspective(
                run,
                kind,
                selection,
                {
                    "status": "FAILED",
                    "findings": "공유 조회 단계에서 분석이 중단됐습니다.",
                    "sources": [],
                    "limitations": list(state.get("warnings", [])),
                },
            )
            updates["results"].update(completed["results"])
            updates["jobs"].update(completed["jobs"])
            updates["warnings"].extend(completed["warnings"])
    return updates


async def generate_report(
    run, *, request, base, documents, context, perspective_results, filing, memo, stage_failed
):
    await run.stage({}, "REPORT_GENERATION")
    original = base or {}
    fragments = context
    proposals = []
    for item in original.get("proposals", []):
        evidence = validated_sources(item.get("evidence", []), documents, fragments)
        before = item.get("before_text", "")
        if (
            item.get("impact_type") != "HOLD"
            and before.strip()
            and before in memo.get("text", "")
            and evidence
        ):
            proposals.append({**item, "evidence": evidence})
    results = {}
    for kind, item in perspective_results.items():
        evidence = validated_sources(item.get("sources", []), documents, fragments)
        completed = item.get("status") == "COMPLETED" and evidence and item.get("findings")
        results[kind] = {
            "perspective_type": kind,
            "status": item.get("status", "FAILED"),
            "findings": item["findings"] if completed else "",
            "sources": evidence if completed else [],
        }
        if item.get("status") == "COMPLETED" and not completed:
            results[kind]["status"] = "INSUFFICIENT_EVIDENCE"
    corrections = []
    for item in filing.get("changes", []):
        verified = validated_sources([item], documents, fragments)
        if verified:
            corrections.append(
                {
                    "label": item["label"],
                    "before": item["before"],
                    "after": item["after"],
                    "source": verified[0],
                }
            )
    evidence = [item["source"] for item in corrections]
    evidence += [s for item in proposals for s in item["evidence"]]
    evidence += [s for item in results.values() for s in item["sources"]]
    evidence = list({source_key(s): s for s in evidence}.values())
    numbered = {f"S{i + 1}": source for i, source in enumerate(evidence)}
    identifiers = {source_key(source): ref for ref, source in numbered.items()}

    def cited(item, sources):
        return {
            **{k: v for k, v in item.items() if k not in {"source", "sources", "evidence"}},
            "evidence_ids": [identifiers[source_key(source)] for source in sources],
        }

    facts = {
        "corrections": [
            cited(
                {key: " ".join(item[key].split()) for key in ("label", "before", "after")},
                [item["source"]],
            )
            for item in corrections
        ],
        "proposals": [cited(item, item["evidence"]) for item in proposals],
        "results": {k: cited(v, v["sources"]) for k, v in results.items() if v["findings"]},
    }
    claims, scenarios, warnings = [], [], []
    for name, label in (("filing", "공시"), ("memo", "메모")):
        if {"filing": filing, "memo": memo}[name].get("error"):
            warnings.append(label + " 조회를 완료하지 못했습니다.")
    if evidence and run.h.ledger.row(run.h.task_id)["turns"] < 7:
        try:
            summary = await run.h.model(
                "report",
                {
                    "request": request,
                    "facts": facts,
                    "evidence": {
                        ref: {**source, "quote": " ".join(source["quote"].split())}
                        for ref, source in numbered.items()
                    },
                },
                ReportSummary,
                report=True,
            )
            for entries, target, key in (
                (summary.summary, claims, "text"),
                (summary.future_impacts, scenarios, "scenario"),
            ):
                for claim in entries:
                    if all(ref in numbered for ref in claim.evidence_ids):
                        target.append(
                            {
                                key: claim.text
                                if key == "text"
                                else f"조건: {claim.condition} 예상 영향: {claim.effect}",
                                "evidence": [numbered[ref] for ref in claim.evidence_ids],
                            }
                        )
                    else:
                        warnings.append("출처가 연결되지 않은 요약을 제외했습니다.")
        except RunCancelled:
            raise
        except Exception:
            warnings.append("요약을 생성하지 못해 확인된 항목만 표시했습니다.")
    selection_sources = validated_sources(filing.get("changes", []), documents, fragments)
    selections = [
        {**item, "evidence": selection_sources[:8]} for item in original.get("selected", [])
    ]
    payload = {
        "request": request,
        "base": {
            "summary": "",
            "proposals": proposals,
            "selected": selections,
            "no_additional_analysis_reason": original.get("no_additional_analysis_reason"),
            "limitations": [],
        },
        "results": results,
        "summary_claims": claims,
        "future_impacts": scenarios,
    }
    checked, check_warnings = await run.h.review_output(
        payload, grounding=True, corrections=corrections
    )
    warnings.extend(check_warnings)
    # 검사에서 이유나 수정문이 제거된 제안은 승인된 제안처럼 표시하지 않습니다.
    checked["base"]["proposals"] = [
        item
        for item in checked["base"]["proposals"]
        if item.get("reason") and (item.get("impact_type") == "NO_IMPACT" or item.get("after_text"))
    ]
    for item in checked["results"].values():
        if item["status"] == "COMPLETED" and not item["findings"]:
            item["status"], item["sources"] = "INSUFFICIENT_EVIDENCE", []
    checked["corrections"] = corrections
    omitted = len(original.get("proposals", [])) - len(checked["base"]["proposals"])
    if omitted:
        warnings.append(
            f"근거 또는 메모 연결이 부족한 수정 제안 {omitted}건을 작성하지 않았습니다."
        )
    if filing.get("changes") and not filing.get("complete_correction_table"):
        warnings.append("정정표 전체 추출을 확인하지 못했습니다.")
    if stage_failed or not original:
        warnings.append("입력 또는 분석 처리 미완료로 확인된 원문만 표시합니다.")
    checked["warnings"] = list(dict.fromkeys(warnings))
    body = compose(checked)
    run.h.ledger.keep(run.h.task_id, "report", body)
    return {"report": body, "warnings": checked["warnings"]}


async def report(run, state):
    """Compatibility entry; canonical nodes pass explicit inputs to the service."""
    return await generate_report(
        run,
        request=state["request"],
        base=state.get("base"),
        documents=state.get("documents", []),
        context=state.get("context", []),
        perspective_results=state.get("results", {}),
        filing=state.get("filing", {}),
        memo=state.get("memo", {}),
        stage_failed=state.get("stage_failed", False),
    )


async def save_report(run, *, report, scope):
    result = await run.h.tool(
        "business_save_report",
        {"task_id": run.h.task_id, "report": report},
        run.tools.call,
        report=True,
        scope=scope,
    )
    if result.get("error"):
        result = {"status": "SAVE_FAILED", "error": result["error"], "report": report}
    else:
        result["report"] = report
    run.h.ledger.keep(run.h.task_id, "result", result)
    return {"output": result}


async def save(run, state):
    """Compatibility entry; canonical nodes pass explicit inputs to the service."""
    return await save_report(run, report=state["report"], scope=state["scope"])


def emergency(run, state, error):
    # 완료 검사를 거치지 못한 모델 문장은 재사용하지 않습니다.
    selected = [
        {"perspective_type": item["perspective_type"], "selection_reason": ""}
        for item in state.get("base", {}).get("selected", [])
    ]
    data = {
        "request": state["request"],
        "base": {"selected": selected, "proposals": []},
        "results": {
            item["perspective_type"]: {"status": "FAILED", "findings": "", "sources": []}
            for item in selected
        },
        "corrections": [],
        "summary_claims": [],
        "warnings": [
            "분석 처리를 완료하지 못해 분석 내용을 작성하지 않았습니다. " + type(error).__name__
        ],
    }
    data["sources"] = validated_sources(
        state.get("context", []), state.get("documents", []), state.get("context", [])
    )
    body = compose(data)
    run.h.ledger.keep(run.h.task_id, "report", body)
    return body
