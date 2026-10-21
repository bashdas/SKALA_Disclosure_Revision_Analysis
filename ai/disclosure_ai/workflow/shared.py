import asyncio

from disclosure_ai.harness.lookup import normalize
from disclosure_ai.services.documents import search_documents
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
            if name == "local_search":
                args = {"query": query}
                if state.get("rag_ready"):
                    name = "search_evidence"
                    args.update(task_id=run.h.task_id, top_k=5)
            else:
                args = {"as_of": state["request"]["disclosure_receipt_no"][:8]}
                if name == "financial":
                    args.update(
                        receipt_no=state["request"]["disclosure_receipt_no"],
                        corp_code=state["request"].get("corp_code"),
                    )
                else:
                    # 메모 원문이 외부 검색어에 포함되지 않도록 공개 연구 주제로 고정합니다.
                    args["query"] = {
                        "INDUSTRY_CONTRACT": "supply contract revision corporate risk",
                        "FINANCE": "financial disclosure restatement earnings quality",
                        "FX_HEDGE": "corporate foreign exchange hedging risk",
                    }[kind]
            pending.append({"kind": kind, "tool": name, "args": normalize(args)})
    return {"lookups": pending}


async def lookup(run, state):
    async def execute(item):
        async def local(_name, args):
            return {"sources": search_documents(state["documents"], args["query"])}

        response = await run.h.tool(
            item["tool"],
            item["args"],
            local if item["tool"] == "local_search" else run.tools.call,
            scope=state["scope"],
        )
        return {**item, "response": response}

    return {"lookup_results": await asyncio.gather(*(execute(item) for item in state["lookups"]))}


async def publish(run, state):
    jobs = {kind: dict(job) for kind, job in state.get("jobs", {}).items()}
    documents = {doc["document_id"]: doc for doc in state["documents"]}
    fragments = list(state["context"])
    results, warnings = {}, []
    for item in state.get("lookup_results", []):
        job = jobs[item["kind"]]
        response = item["response"]
        job["observations"] = [
            *job.get("observations", []),
            {"tool": item["tool"], "result": response},
        ]
        job["limitations"] = list(
            dict.fromkeys(job.get("limitations", []) + response.get("limitations", []))
        )
        if response.get("error"):
            job["limitations"].append(item["tool"] + " 조회 미완료: " + response["error"])
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
