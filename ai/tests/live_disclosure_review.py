"""공개 원문과 합성 메모의 수동 검증입니다. 업무 DB에는 저장하지 않습니다."""

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver

from disclosure_ai.harness.ledger import Ledger
from disclosure_ai.harness.runtime import Harness
from disclosure_ai.workflow.graph import AnalysisGraph


class IsolatedTools:
    def __init__(self, filing, memo):
        self.filing, self.memo, self.calls = filing, memo, []

    async def call(self, name, args):
        self.calls.append(name)
        if name == "disclosure_get_document":
            return self.filing
        if name == "business_get_memo":
            return {"document_id": "memo:synthetic:v1", "text": self.memo, "version": 1}
        if name == "ensure_analysis_index":
            return {"indexed": False, "error": "ISOLATED_TEST_LOCAL_DOCUMENTS_ONLY"}
        if name == "search_market_news":
            return {"articles": [], "documents": [], "sources": [], "limitations": []}
        if name == "business_save_report":
            return {"report_id": args["task_id"], "status": "LOCAL_SAVED"}
        return {"error": "ISOLATED_TEST_LOOKUP_UNAVAILABLE"}


async def main(public, output, only=None):
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    cases = [
        ("public-contract", public, "회사의 국내 신규 공장 건설 현황을 관찰하고 있습니다.", "엘앤에프", "20251229800710"),
        ("synthetic-usd", {"documents": [{"document_id": "filing:usd", "text":
            "검증용 합성 공시입니다. 미국 달러로 지급되는 수출 계약 대금의 지급일을 2026년 11월 30일에서 2027년 2월 28일로 연기합니다. 환헤지 보유 여부와 계약 조건은 기재하지 않았습니다."}],
            "report_name": "대금 지급일 변경", "metadata_status": "FOUND", "changes": []},
         "회사의 국내 신규 공장 건설 현황을 관찰하고 있습니다.", "합성기업", "20261023000001"),
        ("synthetic-ir", {"documents": [{"document_id": "filing:ir", "text":
            "검증용 합성 공시입니다. 기업설명회를 2026년 11월 2일 오후 2시에 온라인으로 개최합니다. 주요 내용은 회사 소개이며 실적 수치와 계약 변경은 발표하지 않았습니다."}],
            "report_name": "기업설명회 개최 안내", "metadata_status": "FOUND", "changes": []},
         "회사의 국내 신규 공장 건설 현황을 관찰하고 있습니다.", "합성기업", "20261023000002"),
    ]
    summaries = []
    for name, filing, memo, company, receipt in cases:
        if only and name not in only:
            continue
        task = str(uuid4())
        book = Ledger(str(output / (name + ".sqlite")))
        book.begin(task, "isolated-disclosure-review-v1")
        harness = Harness(task, book)
        tools = IsolatedTools(filing, memo)
        started = time.monotonic()
        try:
            state = await AnalysisGraph(harness, tools, InMemorySaver()).graph.ainvoke({
                "request": {"analysis_task_id": task, "memo_id": str(uuid4()), "base_memo_version": 1,
                            "disclosure_receipt_no": receipt, "company_name_snapshot": company,
                            "disclosure_type": "NEW", "thread_id": task},
                "scope": "isolated-validation", "warnings": [], "results": {},
            }, {"configurable": {"thread_id": task}, "recursion_limit": 40})
            report = state["report"]
            data = report["report_json"]
            points = data["base"]["review_points"]
            assert len(points) <= 5
            assert all(p["memo_view"] is None for p in points if p["view_type"] == "DISCLOSURE_REVIEW")
            events = [json.loads(e["payload"]) for e in book.events(task) if e["kind"] == "MODEL_END"]
            summary = {"case": name, "model": os.environ.get("OPENAI_MODEL", "gpt-5.4-mini"),
                       "elapsed_seconds": round(time.monotonic() - started, 2),
                       "calls": len(events), "tokens": sum(e["tokens"] for e in events),
                       "roles": [e["role"] for e in events],
                       "reserved_turns": book.row(task)["turns"],
                       "reserved_tokens": book.row(task)["tokens"],
                       "raw_points": len(state.get("base", {}).get("review_points", [])),
                       "points": [{k: p.get(k) for k in ("view_type", "title", "condition", "question")}
                                  for p in points], "warnings": data["warnings"],
                       "tool_calls": tools.calls}
            (output / (name + ".json")).write_text(json.dumps(data, ensure_ascii=False, indent=2))
            (output / (name + ".md")).write_text(report["content"])
            summaries.append(summary)
            (output / "summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2))
            print(json.dumps(summary, ensure_ascii=False), flush=True)
        finally:
            await harness.close()
            book.db.close()


async def check_controls(output):
    """실제 검사 모델이 조건부 질문과 위험한 사실 단정을 구분하는지 확인합니다."""
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    task = str(uuid4())
    book = Ledger(str(output / "controls.sqlite"))
    book.begin(task, "strict-disclosure-controls")
    harness = Harness(task, book)
    source = {"document_id": "filing:control", "location": "line:1", "quote":
              "미국 달러 계약 대금의 지급일을 2026년 11월에서 2027년 2월로 연기합니다."}
    past = {"document_id": "filing:past", "location": "line:1", "quote":
            "2025년 당시의 다른 계약 대금 지급이 완료되었습니다."}
    safe = {"view_type": "DISCLOSURE_REVIEW", "perspective_type": "FX_HEDGE",
            "title": "해당 대금의 헤지 보유가 확인되면 만기를 대조합니다.", "memo_view": None,
            "disclosure_fact": source["quote"],
            "condition": "해당 대금의 환헤지를 보유한 경우입니다.",
            "reason": "환헤지를 보유한 경우 연기된 대금 수취 일정과의 대응을 확인해야 합니다.",
            "question": "해당 대금의 환헤지를 보유한 경우 만기와 금액이 수취 일정에 대응합니까?",
            "check_items": ["해당 대금의 환헤지 보유 여부, 만기와 금액을 확인합니다."], "evidence": [source]}
    invalid = [
        {**safe, "title": "보유 헤지에서 발생한 손실을 반영합니다.", "condition": None,
         "disclosure_fact": "회사는 해당 대금의 환헤지를 보유하며 환손실이 발생했습니다."},
        {**safe, "title": "매출 감소액을 반영합니다.", "condition": None,
         "reason": "이번 변경으로 매출이 10억원 감소했습니다."},
        {**safe, "title": "매수 기회를 활용합니다.", "reason": "지금 해당 종목을 매수하는 것이 적절합니다."},
        {**safe, "title": "이번 대금 지급 완료를 반영합니다.", "condition": None,
         "disclosure_fact": "이번 계약 대금 지급이 완료되었습니다.", "evidence": [source, past]},
    ]
    started = time.monotonic()
    try:
        checked, warnings = await harness.review_output({"base": {"review_points": [safe, *invalid]},
            "filing_facts": [source]}, grounding=True, advisory=True,
            current_document_ids={source["document_id"]})
        remaining = checked["base"]["review_points"]
        assert len(remaining) == 1 and remaining[0]["title"] == safe["title"]
        assert checked["filing_facts"] == [source]
        events = [json.loads(e["payload"]) for e in book.events(task) if e["kind"] == "MODEL_END"]
        result = {"case": "strict-controls", "safe_points": len(remaining), "rejected_points": 4,
                  "calls": len(events), "tokens": sum(e["tokens"] for e in events),
                  "elapsed_seconds": round(time.monotonic() - started, 2), "warnings": warnings}
        (output / "controls.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        await harness.close()
        book.db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-filing", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", action="append", choices=["public-contract", "synthetic-usd", "synthetic-ir"])
    parser.add_argument("--controls-only", action="store_true")
    args = parser.parse_args()
    if args.controls_only:
        asyncio.run(check_controls(args.output))
    else:
        asyncio.run(main(json.loads(args.public_filing.read_text()), args.output, args.case))
