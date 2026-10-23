import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from disclosure_ai.harness.ledger import Ledger
from disclosure_ai.harness.runtime import Harness
from disclosure_ai.services.tools import Tools
from disclosure_ai.workflow import shared, reporting
from disclosure_ai.workflow.perspectives import perspective


async def main():
    fixed = json.loads(INPUT)
    task_id = fixed["task"]["task_id"]
    request = fixed["report"]["report_json"]["request"]
    selection = next(x for x in fixed["report"]["report_json"]["base"]["selected"] if x["perspective_type"] == "MARKET_NEWS")
    ledger = Ledger("/tmp/news-agent-replay-" + task_id + ".sqlite")
    ledger.begin(task_id, "market-agent-live-replay")
    calls, models = [], []
    class RecordingHarness(Harness):
        async def model(self, role, context, schema, report=False):
            result = await super().model(role, context, schema, report)
            models.append({"role": role, "context": context, "output": result.model_dump()})
            return result
    harness = RecordingHarness(task_id, ledger)
    real = Tools("")
    class ReadOnlyTools:
        async def call(self, name, args):
            if name == "business_save_report":
                return {"report_id": "local-validation", "status": "COMPLETED"}
            result = await real.call(name, args)
            calls.append({"name": name, "args": args, "result": result})
            return result
    tools = ReadOnlyTools()
    async def stage(*_):
        return None
    run = SimpleNamespace(h=harness, tools=tools, stage=stage)
    filing = await tools.call("disclosure_get_document", {"receipt_no": request["disclosure_receipt_no"]})
    memo = await tools.call("business_get_memo", {"task_id": task_id, "memo_id": request["memo_id"], "version": request["base_memo_version"]})
    news = await tools.call("search_market_news", {"task_id": task_id, "query": request["company_name_snapshot"] + " 시황", "top_k": 6})
    context = [{"document_id": d["document_id"], "location": "line:1:overview", "quote": d["text"],
                "url": d.get("url"), "published_at": d.get("published_at")} for d in filing["documents"]]
    state = {"request": request, "scope": "market-live-replay", "filing": {**filing, "analysis_type": "NEW"},
             "memo": memo, "documents": filing["documents"] + [memo], "context": context,
             "market_news": news, "selection": selection, "base": {"selected": [selection], "proposals": [],
             "not_selected": [], "limitations": [], "no_additional_analysis_reason": None}, "jobs": {}, "results": {}, "warnings": []}
    for _ in range(4):
        update = await perspective(run, state)
        state.update(update)
        if state.get("results", {}).get("MARKET_NEWS"):
            break
        state.update(await shared.requests(run, state))
        state.update(await shared.lookup(run, state))
        state.update(await shared.publish(run, state))
    result = await reporting.report(run, state)
    print(json.dumps({"real_model": True, "task_bound_live_rag": True,
                      "base_selection_from_actual_task": task_id,
                      "models": models, "tools": calls, "result": state["results"],
                      "report": result["report"], "events": ledger.events(task_id)}, ensure_ascii=False))
    await harness.close()
    ledger.db.close()


asyncio.run(main())
