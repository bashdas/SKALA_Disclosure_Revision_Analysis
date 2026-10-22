import html
import re
from datetime import datetime, timezone

from disclosure_ai.harness.output import safe_text
from disclosure_ai.schemas import ReportSummary
from disclosure_ai.services.business import RunCancelled
from disclosure_ai.services.documents import analysis_context, reference_frames, validated_sources
from disclosure_ai.workflow.perspectives import finish_perspective

PERSPECTIVE_NAMES = {
    "INDUSTRY_CONTRACT": "기업과 산업 및 계약",
    "FINANCE": "재무와 실적",
    "FX_HEDGE": "외부 환경과 위험",
}
STATUS_NAMES = {
    "COMPLETED": "작성 완료",
    "INSUFFICIENT_EVIDENCE": "근거 부족으로 미작성",
    "LIMIT_REACHED": "실행 한도로 미작성",
    "FAILED": "처리 실패로 미작성",
}
SECTION_TITLES = {
    "summary": "핵심 요약",
    "correction": "확인된 공시 내용",
    "memo_impact": "메모 영향",
    "suggestions": "메모 유지 및 수정 제안",
    "perspectives": "관점별 분석",
    "future_impacts": "향후 영향과 조건",
    "limitations": "확인 범위와 남은 질문",
}


def escape(value):
    value = html.escape(str(value), quote=False)
    return re.sub(r"([\\`*_[\]{}|#])", r"\\\1", value)


def source_key(source):
    return source["document_id"], source["location"], source["quote"]


async def join(run, state):
    warnings = list(state.get("base", {}).get("limitations", []))
    if state.get("filing", {}).get("changes") and not state.get("filing", {}).get("complete_correction_table"):
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


async def report(run, state):
    await run.stage(state, "REPORT_GENERATION")
    original = state.get("base") or {}
    documents, fragments = state.get("documents", []), state.get("context", [])
    proposals = []
    for item in original.get("proposals", []):
        evidence = validated_sources(item.get("evidence", []), documents, fragments)
        before = item.get("before_text", "")
        if (
            item.get("impact_type") != "HOLD"
            and before.strip()
            and before in state.get("memo", {}).get("text", "")
            and evidence
        ):
            proposals.append({**item, "evidence": evidence})
    results = {}
    for kind, item in state.get("results", {}).items():
        evidence = validated_sources(item.get("sources", []), documents, fragments)
        completed = item.get("status") == "COMPLETED" and evidence and item.get("findings")
        results[kind] = {
            "perspective_type": kind,
            "status": item.get("status", "FAILED"),
            "findings": item["findings"] if completed else "",
            "sources": evidence if completed else [],
            "limitations": item.get("limitations", []),
        }
        if item.get("status") == "COMPLETED" and not completed:
            results[kind]["status"] = "INSUFFICIENT_EVIDENCE"
    corrections = []
    for item in state.get("filing", {}).get("changes", []):
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
    frames = reference_frames(state.get("filing", {}), state.get("memo", {}))
    evidence = validated_sources(frames["applied_valuation_rows"], documents, fragments)
    evidence += [item["source"] for item in corrections]
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

    scoped_changes = analysis_context(state.get("filing", {}), [c["source"] for c in corrections])
    facts = {
        "corrections": [
            cited(
                scoped,
                [item["source"]],
            )
            for item, scoped in zip(corrections, scoped_changes, strict=True)
        ],
        "proposals": [cited(item, item["evidence"]) for item in proposals],
        "results": {k: cited(v, v["sources"]) for k, v in results.items() if v["findings"]},
    }
    claims, scenarios = [], []
    warnings = list(state.get("warnings", []))
    warnings.extend(original.get("limitations", []))
    for result in state.get("results", {}).values():
        warnings.extend(result.get("limitations", []))
    for name, label in (("filing", "공시"), ("memo", "메모")):
        if state.get(name, {}).get("error"):
            warnings.append(label + " 조회를 완료하지 못했습니다.")
    if evidence and run.h.ledger.row(run.h.task_id)["turns"] < 7:
        try:
            summary = await run.h.model(
                "report",
                {
                    "request": state["request"],
                    "facts": facts,
                    "reference_frames": frames,
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
    selection_sources = validated_sources(
        state.get("filing", {}).get("changes", []), documents, fragments
    )
    selections = [
        {**item, "evidence": selection_sources[:8]} for item in original.get("selected", [])
    ]
    payload = {
        "request": state["request"],
        "base": {
            "summary": "",
            "proposals": proposals,
            "selected": selections,
            "not_selected": original.get("not_selected", []),
            "no_additional_analysis_reason": original.get("no_additional_analysis_reason"),
            "limitations": [],
        },
        "results": results,
        "summary_claims": claims,
        "future_impacts": scenarios,
    }
    checked, check_warnings = await run.h.review_output(
        payload, grounding=True, corrections=corrections, advisory=True
    )
    warnings.extend(check_warnings)
    # 검사에서 이유나 수정문이 제거된 제안은 승인된 제안처럼 표시하지 않습니다.
    checked["base"]["proposals"] = [
        item
        for item in checked["base"]["proposals"]
        if item.get("reason") and (item.get("impact_type") in {"NO_IMPACT", "INTERPRETATION_REVIEW"} or item.get("after_text"))
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
    if state.get("filing", {}).get("changes") and not state.get("filing", {}).get("complete_correction_table"):
        warnings.append("정정표 전체 추출을 확인하지 못했습니다.")
    if state.get("stage_failed") or not original:
        warnings.append("입력 또는 분석 처리 미완료로 확인된 원문만 표시합니다.")
    checked["warnings"] = list(dict.fromkeys(text for w in warnings if (text := safe_text(w))))
    body = compose(checked)
    run.h.ledger.keep(run.h.task_id, "report", body)
    return {"report": body, "warnings": checked["warnings"]}


def compose(data):
    request, base = data["request"], data.get("base") or {}
    selected, results = base.get("selected", []), data.get("results", {})
    all_sources = list(data.get("sources", [])) + [
        item["source"] for item in data.get("corrections", [])
    ]
    all_sources += [s for item in base.get("proposals", []) for s in item["evidence"]]
    all_sources += [s for item in results.values() for s in item["sources"]]
    all_sources += [
        s for item in data.get("summary_claims", []) if item["text"] for s in item["evidence"]
    ]
    all_sources += [
        s for item in data.get("future_impacts", []) if item["scenario"] for s in item["evidence"]
    ]
    sources = list({source_key(s): s for s in all_sources}.values())
    numbers = {source_key(s): i + 1 for i, s in enumerate(sources)}

    def refs(items):
        return " ".join(f"[근거 {numbers[source_key(s)]}]" for s in items)

    sections = {key: "" for key in SECTION_TITLES}
    sections["summary"] = "\n".join(
        "- " + escape(item["text"]) + " " + refs(item["evidence"])
        for item in data.get("summary_claims", [])
        if item["text"]
    )
    sections["future_impacts"] = "\n\n".join(
        "- " + escape(item["scenario"]) + " " + refs(item["evidence"])
        for item in data.get("future_impacts", [])
        if item["scenario"]
    )
    changes = data.get("corrections", [])
    if changes:
        rows = ["| 항목 | 정정 전 | 정정 후 | 근거 |", "| --- | --- | --- | --- |"]
        for item in changes:
            cells = [" ".join(str(item[k]).split()) for k in ("label", "before", "after")]
            # 긴 정정표는 항목별 미리보기와 아래 원문 인용으로 나눠 읽습니다.
            cells = [escape(value[:200] + (" …" if len(value) > 200 else "")) for value in cells]
            rows.append("| " + " | ".join(cells) + " | " + refs([item["source"]]) + " |")
        sections["correction"] = "\n".join(rows)
    proposals = base.get("proposals", [])
    sections["memo_impact"] = "\n".join(
        "- " + escape(item["reason"]) + " " + refs(item["evidence"]) for item in proposals
    )
    suggestions = []
    for i, item in enumerate(proposals):
        before, after = item["before_text"], item.get("after_text")
        keep = item.get("impact_type") == "NO_IMPACT" or (
            after is not None and " ".join(before.split()) == " ".join(after.split())
        )
        if keep:
            suggestions.append(
                f"**유지 제안 {i + 1}**\n\n유지: {escape(before)} {refs(item['evidence'])}"
            )
        elif after:
            suggestions.append(
                f"**수정 제안 {i + 1}**\n\n기존: {escape(before)}\n\n수정: {escape(after)} {refs(item['evidence'])}"
            )
    sections["suggestions"] = "\n\n".join(suggestions)
    sections["perspectives"] = "\n\n".join(
        "### "
        + PERSPECTIVE_NAMES[kind]
        + "\n\n"
        + escape(item["findings"])
        + " "
        + refs(item["sources"])
        for kind, item in results.items()
        if item["status"] == "COMPLETED" and item["findings"]
    )
    statuses = [
        PERSPECTIVE_NAMES[k] + ": " + STATUS_NAMES.get(item["status"], "미작성")
        for k, item in results.items()
        if item["status"] != "COMPLETED"
    ]
    sections["limitations"] = "\n".join(
        "- " + escape(value) for value in [*statuses, *data.get("warnings", [])]
    )
    lines = [
        "# 공시 영향 분석 보고서",
        "",
        "**기업:** " + escape(request["company_name_snapshot"]),
        "",
        "**공시 접수번호:** " + request["disclosure_receipt_no"],
        "",
    ]
    if not sections["summary"]:
        lines += [
            "확인된 공시 내용과 처리 상태를 표시합니다. 근거가 부족한 해석은 작성하지 않았습니다.",
            "",
        ]
    if selected:
        lines += [
            "## 추가 분석을 선택한 이유",
            "",
            "| 관점 | 선택 이유 | 처리 결과 |",
            "| --- | --- | --- |",
        ]
        for item in selected:
            kind = item["perspective_type"]
            reason = (
                " ".join(item.get("selection_reason", "").split())[:140]
                or {
                    "FINANCE": "재무 수치와 메모의 연결 여부를 추가로 확인하기 위해 선택했습니다.",
                    "INDUSTRY_CONTRACT": "산업 및 계약 조건과 메모의 연결 여부를 추가로 확인하기 위해 선택했습니다.",
                    "FX_HEDGE": "외부 환경과 위험에 관한 추가 근거를 확인하기 위해 선택했습니다.",
                }[kind]
            )
            lines.append(
                "| "
                + PERSPECTIVE_NAMES[kind]
                + " | "
                + escape(reason)
                + " | "
                + STATUS_NAMES.get(results.get(kind, {}).get("status"), "미작성")
                + (" (추가 확인 항목 있음)" if results.get(kind, {}).get("status") == "COMPLETED"
                   and results[kind].get("limitations") else "")
                + " |"
            )
        lines.append("")
    else:
        lines += ["추가 관점은 선택되지 않았습니다.", ""]
    omitted = base.get("not_selected", [])
    if omitted:
        lines += ["## 추가 분석을 선택하지 않은 이유", ""]
        lines += [
            "- " + PERSPECTIVE_NAMES[item["perspective_type"]] + ": " + escape(item["reason"])
            for item in omitted
        ]
        lines.append("")
    for name, value in sections.items():
        if value:
            lines += ["## " + SECTION_TITLES[name], "", value, ""]
    if sources:
        lines += ["## 출처와 원문 인용", ""]
        for i, source in enumerate(sources):
            lines += [f"### 근거 {i + 1}", "", "위치: " + escape(source["location"]), ""]
            if source.get("url"):
                lines += [
                    "출처: <" + source["url"].replace("<", "%3C").replace(">", "%3E") + ">",
                    "",
                ]
            quote = " ".join(source["quote"].split())
            lines += ["> " + escape(quote[:800]), ""]
            if len(quote) > 800:
                lines += [
                    "인용 앞부분 800자를 표시했습니다. 전체 원문은 출처에서 확인할 수 있습니다.",
                    "",
                ]
    data["sources"], data["sections"] = sources, sections
    reason = base.get("no_additional_analysis_reason") if not selected else None
    return {
        "content": "\n".join(lines).strip() + "\n",
        "report_json": data,
        "has_warnings": bool(data.get("warnings")) or bool(statuses),
        "no_additional_analysis_reason": reason,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


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
