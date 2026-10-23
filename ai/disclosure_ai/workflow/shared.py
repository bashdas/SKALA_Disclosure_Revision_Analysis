import asyncio

from disclosure_ai.harness.lookup import normalize
from disclosure_ai.services.documents import search_documents
from disclosure_ai.services.history import acquire, merge_history
from disclosure_ai.services.research import search_reports
from disclosure_ai.workflow.perspectives import finish_perspective


def status(state):
    return (
        "KEY"
        if any(job.get("status") == "NEEDS_TOOLS" for job in state.get("jobs", {}).values())
        else "JOIN"
    )


async def requests(run, state):
    pending = []
    for kind, job in state.get("jobs", {}).items():
        if job["status"] != "NEEDS_TOOLS":
            continue
        for lookup in job["requests"]:
            name, query = lookup["tool"], lookup["query"]
            if name == "disclosure_history":
                args = {
                    "reason": query,
                    "receipt_no": lookup.get("receipt_no"),
                    "evidence": lookup.get("evidence", []),
                }
            elif name == "search_market_news":
                args = {
                    "task_id": run.h.task_id,
                    "query": query,
                    "top_k": 6,
                    "days": lookup.get("news_days", 7),
                    "scopes": lookup.get("news_scopes") or None,
                    "topics": lookup.get("news_topics") or None,
                }
                if lookup.get("news_as_of"):
                    args["as_of"] = lookup["news_as_of"]
            elif name == "read_market_news":
                args = {"task_id": run.h.task_id, "article_ids": lookup.get("article_ids", [])}
            elif name == "local_search":
                args = {"query": query}
                if state.get("rag_ready"):
                    name = "search_evidence"
                    args.update(task_id=run.h.task_id, top_k=5)
            else:
                receipt = state["request"]["disclosure_receipt_no"]
                args = {"as_of": f"{receipt[:4]}-{receipt[4:6]}-{receipt[6:8]}"}
                if name == "financial":
                    args.update(
                        corp_code=state["request"].get("corp_code"),
                        bsns_year=lookup.get("bsns_year") or int(receipt[:4]) - 1,
                        reprt_code=lookup.get("reprt_code") or "11011",
                        fs_div=lookup.get("fs_div") or "CFS",
                    )
                else:
                    args["query"] = lookup["query"]
            pending.append({"kind": kind, "tool": name, "args": normalize(args)})
    return {"lookups": pending}


async def lookup(run, state):
    async def execute(item):
        async def local(_name, args):
            return {"sources": search_documents(state["documents"], args["query"])}

        if item["tool"] == "disclosure_history":
            response = await acquire(run, state, item["args"])
        else:
            response = await run.h.tool(
                item["tool"],
                item["args"],
                local if item["tool"] == "local_search" else run.tools.call,
                scope=state["scope"],
            )
        if item["tool"] in {"local_search", "search_evidence"}:
            historical = [d for d in state["documents"] if d.get("history_role")]
            response = {
                **response,
                "sources": [
                    *response.get("sources", []),
                    *search_documents(historical, item["args"]["query"]),
                ],
            }
        if item["tool"] in {"local_search", "search_evidence"} and state.get("research_reports"):
            research = await search_reports(run, state, item["args"]["query"])
            response = {
                **response,
                "documents": response.get("documents", []) + research.get("documents", []),
                "sources": response.get("sources", []) + research.get("sources", []),
                "limitations": response.get("limitations", [])
                + (
                    ["증권사 리포트 추가 검색 미완료: " + research["error"]]
                    if research.get("error")
                    else []
                ),
            }
        return {**item, "response": response}

    return {"lookup_results": await asyncio.gather(*(execute(item) for item in state["lookups"]))}


async def publish(run, state):
    jobs = {kind: dict(job) for kind, job in state.get("jobs", {}).items()}
    documents = {doc["document_id"]: doc for doc in state["documents"]}
    fragments = list(state["context"])
    results, warnings = {}, []
    history = state.get("history", {})
    for item in state.get("lookup_results", []):
        job = jobs[item["kind"]]
        response = item["response"]
        history = merge_history(history, response.get("history", {}))
        job["observations"] = [
            *job.get("observations", []),
            {
                "tool": item["tool"],
                "result": {k: v for k, v in response.items() if k != "documents"},
            },
        ]
        job["limitations"] = list(
            dict.fromkeys(job.get("limitations", []) + response.get("limitations", []))
        )
        if response.get("error"):
            job["limitations"].append(
                ("NEWS_SEARCH_FAILED: " if item["tool"] == "search_market_news" else "")
                + item["tool"]
                + " 조회 미완료: "
                + response["error"]
            )
        for doc in response.get("documents", []):
            if isinstance(doc, dict) and all(
                isinstance(doc.get(k), str) for k in ("document_id", "text")
            ):
                documents[doc["document_id"]] = doc
        fragments.extend(response.get("sources", []))
        if response.get("error") in {"WAIT_LIMIT", "LIMIT_REACHED"}:
            result = await finish_perspective(
                run,
                item["kind"],
                job["selection"],
                {
                    "status": "LIMIT_REACHED",
                    "findings": "조회 실행 또는 대기 한도에 도달했습니다.",
                    "sources": [],
                    "limitations": job["limitations"],
                },
            )
            results.update(result["results"])
            warnings.extend(result["warnings"])
            job["status"] = "LIMIT_REACHED"
        elif job["status"] not in {"LIMIT_REACHED"}:
            job["status"] = "PENDING"
    return {
        "jobs": jobs,
        "history": history,
        "results": results,
        "documents": list(documents.values()),
        "context": fragments,
        "warnings": warnings,
        "lookups": [],
        "lookup_results": [],
    }


def resume(state):
    return (
        "S2"
        if any(job["status"] == "PENDING" for job in state.get("jobs", {}).values())
        else "REPORT_AGENT"
    )
