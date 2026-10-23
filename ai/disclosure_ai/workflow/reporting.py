import html
import re
from datetime import datetime, timezone

from disclosure_ai.harness.output import safe_text
from disclosure_ai.schemas import ReportSummary
from disclosure_ai.services.business import RunCancelled
from disclosure_ai.services.documents import (
    analysis_context,
    reference_frames,
    validated_review_points,
    validated_sources,
)
from disclosure_ai.services.history import ROLES, restore_history, validated_comparisons
from disclosure_ai.services.research import verified_research
from disclosure_ai.workflow.perspectives import finish_perspective

PERSPECTIVE_NAMES = {
    "INDUSTRY_CONTRACT": "기업과 산업 및 계약",
    "FINANCE": "재무와 실적",
    "FX_HEDGE": "외부 환경과 위험",
    "MARKET_NEWS": "시황 뉴스",
}
STATUS_NAMES = {
    "COMPLETED": "작성 완료",
    "INSUFFICIENT_EVIDENCE": "근거 부족으로 미작성",
    "LIMIT_REACHED": "실행 한도로 미작성",
    "FAILED": "처리 실패로 미작성",
}
SECTION_TITLES = {
    "summary": "핵심 요약",
    "review_points": "새롭게 고찰할 관점",
    "history": "조회한 과거 공시와 비교 범위",
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


def report_history(state):
    history = state.get("history", {})
    return {**history, "items": [
        {**{k: v for k, v in item.items() if k != "relation_evidence"},
         "evidence": validated_sources([*item.get("evidence", []), *item.get("relation_evidence", [])],
                                       state.get("documents", []), state.get("context", []))}
        for item in history.get("items", [])
    ]} if history else {}


async def join(run, state):
    warnings = list(state.get("base", {}).get("limitations", []))
    if state.get("filing", {}).get("analysis_type") == "CORRECTION" and not state.get(
        "filing", {}
    ).get("complete_correction_table"):
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
    history = report_history(state)
    comparisons = validated_comparisons(original.get("history_comparisons", []), state)
    review_points = validated_review_points(
        original.get("review_points", []), state.get("filing", {}), state.get("memo", {}),
        documents, fragments,
    )
    research = verified_research(original, state)
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
    memo_review = None
    if not proposals and not review_points and not research["memo_supplements"] and original:
        supplied = original.get("memo_review") or {}
        evidence = validated_sources(supplied.get("evidence", []), documents, fragments)
        reason = supplied.get("reason", "").strip()
        filing_ids = {doc["document_id"] for doc in state.get("filing", {}).get("documents", [])}
        keep = (
            supplied.get("status") == "KEEP"
            and reason
            and any(source["document_id"] in filing_ids for source in evidence)
            and not original.get("proposals")
            and not state.get("stage_failed")
            and state.get("filing", {}).get("analysis_type") != "UNKNOWN"
        )
        memo_review = {
            "status": "KEEP" if keep else "HOLD",
            "reason": reason if reason and (keep or supplied.get("status") == "HOLD") else
                "기존 메모의 관점과 이번 공시를 연결할 근거를 확인하지 못해 재검토 필요성 판단을 보류했습니다. "
                "공시와 기존 메모의 연결 근거를 추가 확인해야 합니다.",
            "evidence": evidence,
        }
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
            results[kind]["limitations"] = [*results[kind]["limitations"], "SOURCE_LINK_FAILED: 보고서에 연결할 원문 출처를 확인하지 못했습니다."]
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
    evidence += [s for item in review_points for s in item["evidence"]]
    evidence += [s for item in history.get("items", []) for s in item["evidence"]]
    evidence += [s for item in comparisons for s in item["evidence"]]
    evidence += [s for item in results.values() for s in item["sources"]]
    evidence += memo_review["evidence"] if memo_review else []
    evidence += [s for items in research.values() for item in items for s in item["evidence"]]
    filing_facts = []
    if state.get("filing", {}).get("analysis_type") != "CORRECTION":
        filing_ids = {d["document_id"] for d in state.get("filing", {}).get("documents", [])}
        filing_facts = validated_sources(
            [s for s in fragments if s.get("document_id") in filing_ids][:4], documents, fragments
        )
        evidence += filing_facts
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
        "analysis_type": state.get("filing", {}).get("analysis_type", "UNKNOWN"),
        "market_as_of": state.get("market_news", {}).get("as_of"),
        "news_retrieval": {k: state.get("market_news", {}).get(k) for k in
            ("as_of", "range_start", "days", "mode", "scopes", "topic_tags", "title_only", "collection", "reason_codes", "limitations")},
        "news_queries": list({str(d["news_retrieval"]): d["news_retrieval"] for d in documents if d.get("news_retrieval")}.values()),
        **{
            key: [cited(item, item["evidence"]) for item in items]
            for key, items in research.items()
        },
        "filing_facts": [cited({}, [source]) for source in filing_facts],
        "memo_review": cited(memo_review, memo_review["evidence"]) if memo_review else None,
        "corrections": [
            cited(
                scoped,
                [item["source"]],
            )
            for item, scoped in zip(corrections, scoped_changes, strict=True)
        ],
        "proposals": [cited(item, item["evidence"]) for item in proposals],
        "review_points": [cited(item, item["evidence"]) for item in review_points],
        "history_comparisons": [cited(item, item["evidence"]) for item in comparisons],
        "disclosure_history": {"status": history.get("status"), "items": [
            cited({key: item.get(key) for key in ("receipt_no", "role", "status", "report_name", "published_at", "relation", "reason")},
                  item["evidence"]) for item in history.get("items", [])]},
        "results": {k: cited(v, v["sources"]) for k, v in results.items() if v["findings"]},
    }
    claims, scenarios = [], []
    warnings = list(state.get("warnings", []))
    warnings.extend(original.get("limitations", []))
    warnings.extend(history.get("limitations", []))
    warnings.extend(state.get("market_news", {}).get("limitations", []))
    for result in state.get("results", {}).values():
        warnings.extend(result.get("limitations", []))
    for name, label in (("filing", "공시"), ("memo", "메모")):
        if state.get(name, {}).get("error"):
            warnings.append(label + " 조회를 완료하지 못했습니다.")
    if evidence and run.h.ledger.row(run.h.task_id)["turns"] < 11:
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
        {**item, "evidence": list({source_key(s): s for s in [
            *selection_sources,
            *(s for point in review_points if point["perspective_type"] == item["perspective_type"]
              for s in point["evidence"]),
        ]}.values())[:8]} for item in original.get("selected", [])
    ]
    payload = {
        "request": state["request"],
        "base": {
            "summary": "",
            "proposals": proposals,
            "review_points": review_points,
            "history_assessment": original.get("history_assessment"),
            "selected": selections,
            "not_selected": original.get("not_selected", []),
            "no_additional_analysis_reason": original.get("no_additional_analysis_reason"),
            "limitations": [],
        },
        "analysis_type": state.get("filing", {}).get("analysis_type", "UNKNOWN"),
        "market_as_of": state.get("market_news", {}).get("as_of"),
        "news_retrieval": {k: state.get("market_news", {}).get(k) for k in
            ("as_of", "range_start", "days", "mode", "scopes", "topic_tags", "title_only", "collection", "reason_codes", "limitations")},
        "news_queries": list({str(d["news_retrieval"]): d["news_retrieval"] for d in documents if d.get("news_retrieval")}.values()),
        "memo_review": memo_review,
        "research_reports": state.get("research_reports", []),
        **research,
        "results": results,
        "summary_claims": claims,
        "future_impacts": scenarios,
        "history_comparisons": comparisons,
    }
    checked, check_warnings = await run.h.review_output(
        payload, grounding=True, corrections=corrections, advisory=True,
        current_document_ids={d["document_id"] for d in state.get("filing", {}).get("documents", [])},
    )
    warnings.extend(check_warnings)
    # 검사에서 이유나 수정문이 제거된 제안은 승인된 제안처럼 표시하지 않습니다.
    checked["base"]["proposals"] = [
        item
        for item in checked["base"]["proposals"]
        if item.get("reason")
        and (
            item.get("impact_type") in {"NO_IMPACT", "INTERPRETATION_REVIEW"}
            or item.get("after_text")
        )
    ]
    checked["base"]["review_points"] = validated_review_points(
        checked["base"]["review_points"], state.get("filing", {}), state.get("memo", {}),
        documents, fragments,
    )
    if not any(item.get("text", "").strip() for item in checked.get("summary_claims", [])):
        # 검사 실패를 '공시 사실이 없음'으로 표시하지 않습니다. 새 해석 대신 검증된 현재 원문만 남깁니다.
        filing_ids = {doc["document_id"] for doc in state.get("filing", {}).get("documents", [])}
        fallback = validated_sources(
            [item["source"] for item in corrections] + filing_facts,
            documents, fragments,
        )
        if not fallback:
            fallback = validated_sources(
                [s for s in fragments if s.get("document_id") in filing_ids], documents, fragments
            )
        unique = {}
        for source in fallback:
            unique.setdefault((source["document_id"], re.sub(r"\s+", "", source["quote"])), source)
        fallback = list(unique.values())
        checked["summary_claims"] = [
            {"text": "공시 원문에서 확인한 내용: " + source["quote"], "evidence": [source]}
            for source in fallback[:2] if source["document_id"] in filing_ids
        ]
        if checked["summary_claims"]:
            warnings.append("SUMMARY_SOURCE_FALLBACK: 해석 요약을 검증하지 못해 확인된 이번 공시 원문 인용을 요약 대신 표시합니다.")
    if not checked["base"]["proposals"] and not checked["base"]["review_points"] and not checked.get("memo_supplements") and (
        not checked.get("memo_review") or not checked["memo_review"].get("reason", "").strip()
    ):
        checked["memo_review"] = {
            "status": "HOLD", "reason": "재검토 관점 또는 수정 제안의 근거를 검증하지 못해 판단을 보류했습니다.",
            "evidence": [],
        }
    for item in checked["results"].values():
        if item["status"] == "COMPLETED" and not item["findings"]:
            item["status"], item["sources"] = "FAILED", []
            item.setdefault("limitations", []).append("OUTPUT_CHECK_FAILED: 출력 검사 후 작성할 서술이 남지 않았습니다.")
    checked["news_snapshots"] = [doc["article_snapshot"] for doc in documents
        if doc.get("article_snapshot") and any(source["document_id"] == doc["document_id"] for source in evidence)]
    checked["corrections"] = corrections
    checked["filing_facts"] = filing_facts
    history["comparisons"] = validated_comparisons(checked.pop("history_comparisons"), state)
    if len(history["comparisons"]) < len(comparisons):
        warnings.append("근거 검사를 통과하지 못한 과거·현재 비교 항목은 보고서에서 제외했습니다.")
    checked["disclosure_history"] = history
    omitted = len(original.get("proposals", [])) - len(checked["base"]["proposals"])
    if omitted:
        warnings.append(
            f"근거 또는 메모 연결이 부족한 수정 제안 {omitted}건을 작성하지 않았습니다."
        )
    if state.get("filing", {}).get("analysis_type") == "CORRECTION" and not state.get(
        "filing", {}
    ).get("complete_correction_table"):
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
    all_sources += data.get("filing_facts", [])
    all_sources += [
        s
        for key in ("memo_supplements", "report_revisions")
        for item in data.get(key, [])
        for s in item["evidence"]
    ]
    all_sources += (data.get("memo_review") or {}).get("evidence", [])
    all_sources += [s for item in base.get("proposals", []) for s in item["evidence"]]
    all_sources += [s for item in base.get("review_points", []) for s in item["evidence"]]
    all_sources += [s for item in data.get("disclosure_history", {}).get("items", []) for s in item.get("evidence", [])]
    all_sources += [s for item in data.get("disclosure_history", {}).get("comparisons", []) for s in item["evidence"]]
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
    history = data.get("disclosure_history", {})
    if history.get("requested"):
        rows = []
        for item in history.get("items", []):
            rows.append("### " + ROLES.get(item["role"], "추가 공시") + " " + escape(item["receipt_no"]))
            if item.get("status") == "ACQUIRED":
                rows.append(escape(item.get("report_name", "")) + " (" + escape(item.get("published_at", "")) + ")")
                rows.append("연결 근거: " + escape(item.get("relation", "")) + " " + refs(item["evidence"]))
                if item.get("relation_url"):
                    rows.append("[DART 연결 목록 확인](" + item["relation_url"] + ")")
                rows.append("확인 범위: 원문을 확보했습니다. 아래 분석에서 실제 인용한 계약 대상, 물량, 금액, 기간과 조건의 범위를 확인합니다. 원문 확보가 모든 조건의 확인을 뜻하지는 않습니다.")
            else:
                rows.append("비교 미완료: " + escape(item.get("reason", "원문을 확보하지 못했습니다.")))
        if not rows:
            rows.append("비교에 사용할 과거 공시 원문을 확보하지 못했습니다.")
        for item in history.get("comparisons", []):
            rows.extend(["### 비교 항목: " + escape(item["subject"]),
                         "**과거 공시:** " + escape(item["past_fact"]),
                         "**이번 공시:** " + escape(item["current_fact"]),
                         "**비교 결과와 확인 범위:** " + escape(item["interpretation"]) + " " + refs(item["evidence"])])
        if any(item.get("status") == "ACQUIRED" for item in history.get("items", [])) and not history.get("comparisons"):
            rows.append("과거 원문은 확보했지만 양쪽 근거가 연결된 비교 결과는 작성되지 않았습니다. 원문 확보와 비교 완료를 구분합니다.")
        rows.extend(escape(value) for value in history.get("limitations", []))
        rows.extend(escape(value) for value in history.get("notes", []))
        sections["history"] = "\n\n".join(rows)
    sections["summary"] = "\n".join(
        "- " + escape(item["text"]) + " " + refs(item["evidence"])
        for item in data.get("summary_claims", [])
        if item["text"]
    )
    sections["review_points"] = "\n\n".join(
        f"### {i + 1}. {escape(point['title'])}\n\n"
        + ("**유형:** 새로운 검토 관점\n\n" if point.get("view_type") == "DISCLOSURE_REVIEW"
           else "**유형:** 기존 관점 재검토\n\n"
           f"**기존 메모의 관점과 가정:** {escape(point['memo_view'])}\n\n")
        + f"**새 공시에서 확인한 사실:** {escape(point['disclosure_fact'])}\n\n"
        + (f"**검토 조건:** {escape(point['condition'])}\n\n" if point.get("condition") else "")
        + f"**다시 고찰할 이유:** {escape(point['reason'])}\n\n"
        f"**검토 질문:** {escape(point['question'])}\n\n"
        + "**확인할 자료와 조건:**\n\n"
        + "\n".join("- " + escape(item) for item in point["check_items"])
        + "\n\n" + refs(point["evidence"])
        for i, point in enumerate(base.get("review_points", []))
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
    elif data.get("filing_facts"):
        sections["correction"] = "\n\n".join(
            escape(" ".join(source["quote"].split())[:500]) + " " + refs([source])
            for source in data["filing_facts"]
        )
    proposals = base.get("proposals", [])
    sections["memo_impact"] = "\n".join(
        "- "
        + ("수정 없음: " if item.get("impact_type") == "NO_IMPACT" else "")
        + escape(item["reason"])
        + " "
        + refs(item["evidence"])
        for item in proposals
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
    if not proposals and not base.get("review_points") and not data.get("memo_supplements"):
        decision = data.get("memo_review") or {
            "status": "HOLD", "reason": "현재 자료에서 기존 관점의 재검토 필요성을 판단할 근거가 부족합니다.",
            "evidence": [],
        }
        data["memo_review"] = decision
        label = "기존 메모 유지" if decision["status"] == "KEEP" else "메모 영향 판단 보류"
        suggestions.append(
            f"**{label}**\n\n{escape(decision['reason'])} {refs(decision.get('evidence', []))}"
        )
    for item in data.get("memo_supplements", []):
        suggestions.append(
            "**메모 보완 제안**\n\n추가 내용: "
            + escape(item["text"])
            + "\n\n이유: "
            + escape(item["reason"])
            + " "
            + refs(item["evidence"])
        )
    titles = {item["document_id"]: item["title"] for item in data.get("research_reports", [])}
    for item in data.get("report_revisions", []):
        value = "**증권사 리포트 수정 검토**\n\n리포트: " + escape(
            titles.get(item["document_id"], item["document_id"])
        )
        value += (
            "\n\n위치: " + escape(item["location"]) + "\n\n기존: " + escape(item["before_text"])
        )
        if item.get("after_text"):
            value += "\n\n수정안: " + escape(item["after_text"])
        value += "\n\n검토 이유: " + escape(item["reason"]) + " " + refs(item["evidence"])
        suggestions.append(value)
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
    if data.get("market_as_of") and any(item.get("perspective_type") == "MARKET_NEWS" for item in selected):
        lines += ["**시황 기준 시각(분석 요청):** " + escape(data["market_as_of"]), ""]
        news = data.get("news_retrieval", {})
        lines += ["**뉴스 조회 범위:** " + escape(str(news.get("range_start") or "미확인")) + "부터 기준 시각까지입니다. 제목만 수집했습니다.", ""]
        for query in data.get("news_queries", []):
            if query.get("as_of") != data["market_as_of"]:
                lines += ["추가 뉴스 조회: " + escape(str(query.get("range_start"))) + "부터 " + escape(str(query.get("as_of"))) + "까지입니다.", ""]
    if not sections["summary"]:
        lines += [
            "확인된 공시 내용과 처리 상태를 표시합니다. 근거가 부족한 해석은 작성하지 않았습니다.",
            "",
        ]
    chosen = {item["perspective_type"]: item for item in selected}
    omitted = {item["perspective_type"]: item for item in base.get("not_selected", [])}
    lines += [
        "## 관점 선택과 이유",
        "",
        "| 관점 | 선택 여부 | 이유 | 처리 결과 |",
        "| --- | --- | --- | --- |",
    ]
    for kind, label in PERSPECTIVE_NAMES.items():
        item = chosen.get(kind) or omitted.get(kind)
        selected_here = kind in chosen
        reason = item.get("selection_reason" if selected_here else "reason") if item else None
        reason = reason or "이 관점의 판단 이유가 저장되지 않았습니다."
        status = (
            STATUS_NAMES.get(results.get(kind, {}).get("status"), "미작성")
            if selected_here
            else "해당 없음"
        )
        if (
            selected_here
            and results.get(kind, {}).get("status") == "COMPLETED"
            and results[kind].get("limitations")
        ):
            status += " (추가 확인 항목 있음)"
        lines.append(
            "| "
            + label
            + " | "
            + ("선택" if selected_here else "미선택" if item else "판단 기록 없음")
            + " | "
            + escape(reason)
            + " | "
            + status
            + " |"
        )
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
    restored = restore_history(run.h, state)
    documents = list({d["document_id"]: d for d in
                      [*state.get("documents", []), *restored["documents"]]}.values())
    historical_sources = [s for item in restored["history"].get("items", []) for s in item.get("evidence", [])]
    state = {**state, "documents": documents, "history": restored["history"],
             "context": [*state.get("context", []), *historical_sources]}
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
        "disclosure_history": report_history(state),
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
