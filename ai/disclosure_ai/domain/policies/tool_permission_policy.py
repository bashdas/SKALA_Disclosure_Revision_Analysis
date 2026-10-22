def prepare_lookup(definition, lookup, request, *, task_id, rag_ready):
    """Allow only tools registered for this perspective before building provider arguments."""
    if lookup["tool"] not in definition.allowed_tools:
        raise ValueError("TOOL_NOT_ALLOWED")
    name, query = lookup["tool"], lookup["query"]
    if name == "local_search":
        args = {"query": query}
        if rag_ready:
            name = "search_evidence"
            args.update(task_id=task_id, top_k=5)
    else:
        receipt = request["disclosure_receipt_no"]
        args = {"as_of": f"{receipt[:4]}-{receipt[4:6]}-{receipt[6:8]}"}
        if name == "financial":
            args.update(
                corp_code=request.get("corp_code"),
                bsns_year=lookup.get("bsns_year") or int(receipt[:4]) - 1,
                reprt_code=lookup.get("reprt_code") or "11011",
                fs_div=lookup.get("fs_div") or "CFS",
            )
        else:
            # 메모 원문이 외부 검색어에 포함되지 않도록 공개 연구 주제로 고정합니다.
            args["query"] = definition.academic_query
    return name, args
