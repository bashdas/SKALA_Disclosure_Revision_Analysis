import html
import re
from datetime import datetime, timezone

from disclosure_ai.analysis.perspectives.registry import DEFAULT_REGISTRY

PERSPECTIVE_NAMES = DEFAULT_REGISTRY.titles()
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
    "suggestions": "메모 수정 제안",
    "perspectives": "관점별 분석",
    "future_impacts": "향후 영향과 조건",
    "limitations": "확인 범위와 남은 질문",
}


def escape(value):
    value = html.escape(str(value), quote=False)
    return re.sub(r"([\\`*_[\]{}|#])", r"\\\1", value)


def source_key(source):
    return source["document_id"], source["location"], source["quote"]


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
    sections["suggestions"] = "\n\n".join(
        f"**제안 {i + 1}**\n\n기존: {escape(item['before_text'])}\n\n수정: {escape(item['after_text'])} {refs(item['evidence'])}"
        for i, item in enumerate(proposals)
        if item.get("after_text")
    )
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
                + " |"
            )
        lines.append("")
    else:
        lines += ["추가 관점은 선택되지 않았습니다.", ""]
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
