from langgraph.graph import END
from langgraph.types import Send

from disclosure_ai.business import RunCancelled
from disclosure_ai.documents import search_documents, validated_sources
from disclosure_ai.schemas import PerspectiveAnswer


def selected(state):
    selected = state.get("base", {}).get("selected", [])
    if not selected:
        return END
    return [Send("perspective", {**state, "selection": selection}) for selection in selected]


async def register(run, state):
    await run.stage(state, "PERSPECTIVE_ANALYSIS", {"selected": state["base"]["selected"]})
    return {}


async def perspective(run, state):
    selection = state["selection"]
    kind = selection["perspective_type"]
    documents = list(state["documents"])
    fragments = list(state["context"])
    observations = []
    lookup_limits = []
    try:
        if hasattr(run.tools, "perspective"):
            await run.tools.perspective(run.h.task_id, selection)
        for _ in range(3):
            answer = await run.h.model(
                "perspective",
                {
                    "selection": selection,
                    "base": state["base"],
                    "context": state["context"],
                    "observations": observations,
                },
                PerspectiveAnswer,
            )
            result = answer.model_dump()
            if result["status"] != "NEEDS_TOOLS":
                result["limitations"] = list(dict.fromkeys(result["limitations"] + lookup_limits))
                result["sources"] = validated_sources(result["sources"], documents, fragments)
                if not result["sources"]:
                    result["status"] = "INSUFFICIENT_EVIDENCE"
                    result["limitations"].append("검증 가능한 출처가 없습니다.")
                return await finish_perspective(run, kind, selection, result)
            if not result["requests"]:
                break
            for lookup in result["requests"]:
                name, query = lookup["tool"], lookup["query"]
                if name == "local_search" and state.get("rag_ready"):
                    response = await run.h.tool(
                        "search_evidence",
                        {"task_id": run.h.task_id, "query": query, "top_k": 5},
                        run.tools.call,
                        scope=state["scope"],
                    )
                elif name == "local_search":

                    async def local_call(_name, args):
                        return {"sources": search_documents(documents, args["query"])}

                    response = await run.h.tool(
                        name, {"query": query}, local_call, scope=state["scope"]
                    )
                else:
                    # 외부에는 공개 공시 식별자와 관점별 학술 검색어만 보냅니다.
                    args = {"as_of": state["request"]["disclosure_receipt_no"][:8]}
                    if name == "financial":
                        args.update(
                            receipt_no=state["request"]["disclosure_receipt_no"],
                            corp_code=state["request"].get("corp_code"),
                        )
                    else:
                        args["query"] = {
                            "INDUSTRY_CONTRACT": "supply contract revision corporate risk",
                            "FINANCE": "financial disclosure restatement earnings quality",
                            "FX_HEDGE": "corporate foreign exchange hedging risk",
                        }[kind]
                    response = await run.h.tool(name, args, run.tools.call, scope=state["scope"])
                lookup_limits.extend(response.get("limitations", []))
                if response.get("error"):
                    lookup_limits.append(name + " 조회 미완료: " + str(response["error"]))
                observations.append({"tool": name, "result": response})
                fragments.extend(response.get("sources", []))
                for doc in response.get("documents", []):
                    if isinstance(doc, dict) and all(
                        isinstance(doc.get(k), str) for k in ("document_id", "text")
                    ):
                        documents.append(doc)
        result = {
            "status": "LIMIT_REACHED",
            "findings": "추가 분석 반복 한도에 도달했습니다.",
            "sources": [],
            "limitations": ["관점별 모델 호출은 최대 3회입니다."],
        }
    except RunCancelled:
        raise
    except Exception as error:
        result = {
            "status": "LIMIT_REACHED" if type(error).__name__ == "LimitReached" else "FAILED",
            "findings": "추가 분석을 완료하지 못했습니다.",
            "sources": [],
            "limitations": [type(error).__name__],
        }
    result["limitations"] = list(dict.fromkeys(result["limitations"] + lookup_limits))
    return await finish_perspective(run, kind, selection, result)


async def finish_perspective(run, kind, selection, result):
    if hasattr(run.tools, "perspective"):
        await run.tools.perspective(run.h.task_id, selection, result)
    return {"results": {kind: {**selection, **result}}}
