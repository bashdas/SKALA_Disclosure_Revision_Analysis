"""작업 범위 안에서 DART 연결 이력과 현재 본문이 명시한 원공시만 확보합니다."""

import asyncio
import copy
import re
from datetime import date, datetime

from disclosure_ai.harness.lookup import cache_key
from disclosure_ai.services.business import RunCancelled
from disclosure_ai.services.documents import search_documents, validated_sources

ROLES = {"ORIGINAL": "최초 공시", "PREVIOUS": "직전 공시", "ADDITIONAL": "추가 공시"}
REFERENCE = re.compile(r"관련\s*공시|최초\s*(?:공시|제출)|정정\s*대상|원\s*공시|기\s*공시|공시\s*(?:일|날짜|서류)|공시한|공시했던|공시된")
DATES = re.compile(r"(20\d{2})\s*(?:[-./]|년)\s*(\d{1,2})\s*(?:[-./]|월)\s*(\d{1,2})(?:\s*일)?")
IDENTITY = re.compile(r"계약\s*상대(?:방)?|거래\s*상대(?:방)?|계약(?:의)?\s*(?:대상|내용)|품목|제품명|공급\s*제품")


def compact(value):
    return re.sub(r"[^가-힣A-Za-z0-9]", "", value)


def explicit_references(filing, current):
    refs = {}
    for doc in filing.get("documents", []):
        lines = doc["text"].splitlines()
        for i, line in enumerate(lines):
            start = max(0, i - 1)
            quote = "\n".join(lines[start:min(len(lines), i + 2)])
            source = {"document_id": doc["document_id"], "location": f"line:{start + 1}",
                      "quote": quote, "url": doc.get("url"), "published_at": doc.get("published_at")}
            for match in re.finditer(r"(?<!\d)(20\d{12})(?!\d)", line):
                receipt = match[1]
                try:
                    datetime.strptime(receipt[:8], "%Y%m%d")
                except ValueError:
                    continue
                prefix = line[max(0, match.start() - 40):match.start()]
                labelled = re.search(r"(?:rcpNo|rcept_no)\s*=\s*$|(?:접수(?:번호)?|공시번호|원\s*공시|관련\s*공시|정정\s*대상)\s*[:：]?\s*$", prefix, re.I)
                if receipt < current and labelled:
                    refs[("receipt", receipt)] = {"receipt_no": receipt, "source": source}
            if not REFERENCE.search(quote):
                continue
            for match in DATES.finditer(line):
                try:
                    value = date(*map(int, match.groups())).isoformat()
                    cutoff = datetime.strptime(current[:8], "%Y%m%d").date().isoformat()
                except ValueError:
                    continue
                if value <= cutoff:
                    refs[("date", value)] = {"date": value, "source": source}
    return list(refs.values())


def identity_terms(text):
    values = set()
    for line in text.splitlines():
        match = IDENTITY.search(line)
        if match:
            tail = line[match.end():].strip(" :|\t-ㆍ")
            if (tail and not tail.startswith("의")
                    and not re.search(r"비공개|영업비밀|미정|해당없|공시유보|변경없|변동없|미기재|미공개|미해당", tail)):
                values.update(re.findall(r"[가-힣]{3,}|[A-Za-z][A-Za-z0-9-]{2,}", tail.casefold()))
    # 본문 서술에만 등장하는 영문 계약 상대방도 사용할 수 있습니다.
    values.update(word.casefold() for word in re.findall(r"\b[A-Z][a-z][A-Za-z-]{2,}\b", text))
    for match in re.finditer(r"([가-힣A-Za-z0-9-]{2,}(?:\s+[가-힣A-Za-z0-9-]{2,}){0,2})\s+(?:공급|판매|구매)\s*계약", text):
        values.update(word.casefold() for word in match[1].split() if len(word) >= 3)
    return values - {"계약금액", "계약기간", "공급계약", "계약체결", "단일판매", "계약상대방", "주식회사",
                     "공급물량", "변경사항", "해당사항", "양극재", "정정사항은", "상기계약은", "inc", "ltd", "corp", "the", "usd", "krw",
                     "contract", "company", "date", "amount", "original", "supply", "related", "disclosure", "report", "information",
                     "none", "applicable", "document", "market", "business"}


def original_reference(title, quote):
    if re.search(r"정정|변경|해지", title):
        return False
    if re.search(r"최초\s*(?:공시|제출)|원\s*공시|정정\s*대상", quote):
        return True
    # 본문이 특정 날짜의 계약 체결 공시를 명시하고 동일 대상을 대조한 경우입니다.
    return "계약체결" in compact(title) and "계약체결" in compact(quote)


def history_sources(document):
    # 개요와 계약 관련 원문 줄을 함께 보존하며 과거 정정표를 현재 정정표로 합치지 않습니다.
    rows = [{"document_id": document["document_id"], "location": "line:1:history",
             "quote": document["text"][:900], "url": document.get("url"),
             "published_at": document.get("published_at")}]
    rows += search_documents([document], "계약 상대방 물량 금액 기간 인도 제품 해지 변경 정정", limit=5)
    return validated_sources(rows, [document], rows)


def merge_history(left, right):
    if not left:
        return copy.deepcopy(right)
    if not right:
        return copy.deepcopy(left)
    result = {**left, **right}
    for key in ("items", "candidates"):
        result[key] = list({item["receipt_no"]: item for item in
                            [*left.get(key, []), *right.get(key, [])]}.values())
    for key in ("limitations", "notes"):
        result[key] = list(dict.fromkeys([*left.get(key, []), *right.get(key, [])]))
    return result


def model_history(history):
    """원문은 history_context에만 보내고 조회 상태와 후보 목록의 중복 인용을 줄입니다."""
    return {"status": history.get("status"), "limitations": history.get("limitations", []),
            "items": [{k: item.get(k) for k in ("receipt_no", "role", "status", "report_name", "published_at", "document_id", "relation")}
                      for item in history.get("items", [])],
            "candidates": history.get("candidates", [])}


def validated_comparisons(items, state):
    current_ids = {d["document_id"] for d in state.get("filing", {}).get("documents", [])}
    known = {item["receipt_no"]: item.get("document_id") for item in state.get("history", {}).get("items", [])
             if item.get("status") == "ACQUIRED"}
    result = []
    for item in items:
        sources = validated_sources(item.get("evidence", []), state.get("documents", []), state.get("context", []))
        ids = {s["document_id"] for s in sources}
        if (known.get(item.get("receipt_no")) in ids and current_ids & ids
                and all(item.get(k, "").strip() for k in ("subject", "past_fact", "current_fact", "interpretation"))):
            result.append({**item, "evidence": sources})
    return result


def restore_history(harness, state):
    history = merge_history(state.get("history", {}), harness.ledger.history_snapshot(harness.task_id))
    documents = {d["document_id"]: d for d in state.get("documents", []) if d.get("history_role")}
    for item in history.get("items", []):
        if item.get("status") != "ACQUIRED" or item.get("document_id") in documents:
            continue
        key = cache_key(state.get("scope", ""), "history_document", {"receipt_no": item["receipt_no"]})
        cached = harness.ledger.cached(harness.task_id, key)
        if cached:
            for doc in cached.get("documents", []):
                if doc["document_id"] == item.get("document_id"):
                    documents[doc["document_id"]] = {**doc, "history_role": item["role"],
                        "receipt_no": item["receipt_no"], "report_name": item.get("report_name"),
                        "published_at": item.get("published_at")}
    return {"history": history, "documents": list(documents.values())}


async def acquire(run, state, request=None, *, automatic=False):
    """기준 원문은 공유 잠금, 영속 예산, 기존 조회 캐시를 거쳐 수집합니다."""
    current = state["request"]["disclosure_receipt_no"]
    if not re.fullmatch(r"[0-9]{14}", current):
        return {"documents": [], "sources": [], "history": {"status": "NOT_SUPPORTED", "items": [],
                "limitations": ["과거 공시 자동 조회는 국내 OpenDART 공시를 대상으로 합니다."]}}
    async with run.h.history_lock:
        restored = restore_history(run.h, state)
        history = merge_history(restored["history"], run.h.history_data)
        history.update(requested=True)
        history.setdefault("items", [])
        history.setdefault("candidates", [])
        history.setdefault("limitations", [])
        documents = {d["document_id"]: d for d in restored["documents"]}
        sources = []

        def limit(message):
            if message not in history["limitations"]:
                history["limitations"].append(message)

        def record(receipt, **values):
            row = next((x for x in history["items"] if x["receipt_no"] == receipt), None)
            if row is None:
                row = {"receipt_no": receipt, "role": "ADDITIONAL", "evidence": []}
                history["items"].append(row)
            row.update(values)
            return row

        current_docs = state["filing"].get("documents", [])
        refs = explicit_references(state["filing"], current)
        corpus = "\n".join(d["text"] for d in current_docs)
        corp = state["request"].get("corp_code") or state["filing"].get("corp_code")
        current_sources = state.get("context", [])
        requested_receipt = (request or {}).get("receipt_no")
        request_sources = validated_sources((request or {}).get("evidence", []), current_docs, current_sources)
        if not automatic and not request_sources:
            history["status"] = "UNAVAILABLE"
            limit("과거 공시 조회 요청을 뒷받침하는 이번 공시의 원문 근거를 확인하지 못했습니다.")
            return {"documents": [], "sources": [], "history": history}
        if not corp:
            history["status"] = "UNAVAILABLE"
            limit("기업코드를 확인하지 못해 과거 공시를 자동으로 연결하지 않았습니다.")
            return {"documents": [], "sources": [], "history": history}
        remaining = run.h.ledger.begin_history(run.h.task_id)
        remaining = min(remaining, max(0, run.h.remaining() - 12))
        semaphore = asyncio.Semaphore(2)

        async def call(name, args):
            return await run.h.tool(name, args, run.tools.call, scope=state["scope"])

        async def fetch(candidate, role, relation, *, verify_identity=False):
            receipt = candidate["receipt_no"]
            existing = next((d for d in documents.values() if d.get("receipt_no") == receipt), None)
            if existing:
                return existing
            row = record(receipt, role=role, report_name=candidate.get("report_name", ""),
                         status="PENDING", relation=relation, relation_evidence=candidate.get("evidence", []),
                         relation_url=candidate.get("relation_url"))
            if not re.fullmatch(r"[0-9]{14}", receipt) or receipt >= current:
                row.update(status="EXCLUDED", reason="현재 공시 이전의 공시가 아닙니다.")
                return None
            if not run.h.ledger.reserve_history_document(run.h.task_id, receipt):
                row.update(status="LIMIT_REACHED", reason="과거 원문 조회 한도 3건에 도달했습니다.")
                limit(row["reason"])
                return None
            async with semaphore:
                result = await call("history_document", {"receipt_no": receipt})
            if result.get("error") or not result.get("documents"):
                row.update(status="UNAVAILABLE", reason="원문을 확보하지 못했습니다: " + str(result.get("error", "EMPTY_DOCUMENT")))
                limit(row["reason"])
                return None
            published = result.get("filed_at")
            if (result.get("corp_code") != corp or result.get("metadata_status") != "FOUND"
                    or not isinstance(result.get("report_name"), str) or not result["report_name"].strip()
                    or not published or published.replace("-", "") != receipt[:8]):
                row.update(status="EXCLUDED", reason="공시의 회사 또는 공개 시점을 확인하지 못했습니다.")
                limit(row["reason"])
                return None
            doc = {**result["documents"][0], "receipt_no": receipt, "history_role": role,
                   "report_name": result.get("report_name", ""), "published_at": published}
            if verify_identity:
                anchors = identity_terms(corpus)
                normalized = re.sub(r"\s+", "", doc["text"]).casefold()
                if not anchors or not any(term in normalized for term in anchors):
                    row.update(status="RELATION_UNCONFIRMED", reason="같은 날짜의 공시이지만 계약 상대방 또는 대상을 대조하지 못했습니다.")
                    return None
            row.update(report_name=doc["report_name"], published_at=published, status="FETCHED")
            return doc

        def accept(doc):
            receipt = doc["receipt_no"]
            evidence = history_sources(doc)
            row = record(receipt, status="ACQUIRED", document_id=doc["document_id"], evidence=evidence,
                         reason="원문을 확보했습니다. 계약 대상·물량·금액·기간·인도 조건 중 원문에서 확인되는 범위를 비교합니다.")
            # 날짜 참조로 찾은 정정공시를 최초 공시로 표시하지 않습니다.
            if row["role"] == "ORIGINAL" and re.match(r"^\[(?:기재|첨부)?정정\]", doc["report_name"]):
                row["role"] = doc["history_role"] = "ADDITIONAL"
            documents[doc["document_id"]] = doc
            sources.extend(evidence)
            run.h.ledger.save_history(run.h.task_id, history)

        try:
            if remaining <= 0:
                limit("과거 공시 조회 시간 한도에 도달해 확보된 자료만 사용합니다.")
            else:
                async with asyncio.timeout(remaining):
                    family = await call("history_family", {"receipt_no": current})
                    if family.get("error"):
                        limit("DART 연결 공시 목록을 확보하지 못했습니다: " + family["error"])
                    elif (family.get("source_url") != f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={current}"
                          or not any(r.get("receipt_no") == current for r in family.get("items", []))):
                        limit("현재 공시가 포함된 공식 연결 목록인지 확인하지 못했습니다.")
                        family = {"items": []}
                    family_rows = [r for r in family.get("items", []) if
                                   isinstance(r.get("receipt_no"), str)
                                   and re.fullmatch(r"[0-9]{14}", r["receipt_no"])
                                   and r["receipt_no"] < current
                                   and r.get("filed_at", "").replace("-", "") == r["receipt_no"][:8]]
                    family_rows.sort(key=lambda r: r["receipt_no"])
                    family_rows = [{**r, "relation_url": family.get("source_url")} for r in family_rows]
                    history["candidates"] = list({r["receipt_no"]: r for r in
                                                  [*history["candidates"], *family_rows[:1], *family_rows[-19:]]}.values())
                    available = {r["receipt_no"]: r for r in history["candidates"]}
                    direct = {r["receipt_no"] for r in refs if r.get("receipt_no")}
                    if requested_receipt and requested_receipt not in direct and requested_receipt not in available:
                        note = "요청 접수번호는 원문에서 확인되지 않아 사용하지 않고 본문에 명시된 공시 참조만 추적했습니다."
                        history["notes"] = list(dict.fromkeys([*history.get("notes", []), note]))
                        requested_receipt = None
                    original = next((r for r in family_rows if r.get("is_correction") is False), None)
                    previous = family_rows[-1] if family_rows else None
                    targets = {}
                    if requested_receipt:
                        match = available.get(requested_receipt)
                        if match:
                            role = ("ORIGINAL" if original and match == original else
                                    "PREVIOUS" if previous and match == previous else "ADDITIONAL")
                            targets[requested_receipt] = (match, role, "DART 연결 공시 목록")
                    else:
                        if original:
                            targets[original["receipt_no"]] = (original, "ORIGINAL", "DART 연결 공시 목록")
                        if previous and previous["receipt_no"] not in targets:
                            targets[previous["receipt_no"]] = (previous, "PREVIOUS", "DART 연결 공시 목록")
                    async def fetch_and_accept(target):
                        doc = await fetch(*target)
                        if doc:
                            accept(doc)
                    await asyncio.gather(*(fetch_and_accept(target) for target in targets.values()))
                    # 본문의 명시적인 접수번호는 연결 목록 밖이라도 같은 회사의 원문을 조회합니다.
                    for ref in [r for r in refs if r.get("receipt_no")][:3]:
                        receipt = ref["receipt_no"]
                        if requested_receipt and receipt != requested_receipt:
                            continue
                        role = "ORIGINAL" if re.search(r"최초|원공시|정정\s*대상", ref["source"]["quote"]) else "ADDITIONAL"
                        doc = await fetch({"receipt_no": receipt, "evidence": [ref["source"]]},
                                          role, "이번 공시 본문의 접수번호 또는 DART 링크")
                        if doc:
                            accept(doc)
                    need_dates = not any(r.get("role") == "ORIGINAL" and r.get("status") == "ACQUIRED" for r in history["items"])
                    if need_dates or not automatic or requested_receipt:
                        for ref in [r for r in refs if r.get("date")][:3]:
                            rows, page = [], 1
                            while page <= 3:
                                found = await call("history_search", {"corp_code": corp,
                                    "start_date": ref["date"], "end_date": ref["date"], "page": page, "query": ""})
                                if found.get("error"):
                                    limit("본문에 명시된 공시일의 목록 조회를 완료하지 못했습니다.")
                                    rows = []
                                    break
                                rows.extend(found.get("items", []))
                                if not found.get("has_more"):
                                    break
                                page += 1
                            if found.get("has_more"):
                                limit("동일 공시일의 후보 목록을 모두 확인하지 못해 원공시 연결을 보류했습니다.")
                                continue
                            candidates = list({r["receipt_no"]: {**r, "evidence": [ref["source"]]} for r in rows
                                if r.get("corp_code") == corp and re.fullmatch(r"[0-9]{14}", r.get("receipt_no", ""))
                                and r["receipt_no"] < current and r.get("filed_at") == ref["date"]}.values())
                            # 명시된 문서명은 후보를 줄이는 데만 사용하고 본문 대조는 별도로 합니다.
                            named = [r for r in candidates if len(compact(r.get("report_name", ""))) >= 5
                                     and compact(r["report_name"]) in compact(ref["source"]["quote"])]
                            if named:
                                candidates = named
                            if requested_receipt:
                                candidates = [r for r in candidates if r["receipt_no"] == requested_receipt]
                            if not candidates or len(candidates) > 3:
                                limit("본문 공시일의 원공시 후보를 특정하지 못했습니다.")
                                continue
                            reserved = set(run.h.ledger.history_receipts(run.h.task_id))
                            if len(reserved | {r["receipt_no"] for r in candidates}) > 3:
                                limit("원문 조회 한도 내에서 후보 전체를 대조할 수 없어 원공시 연결을 보류했습니다.")
                                continue
                            matched = await asyncio.gather(*(fetch(r, "ADDITIONAL", "이번 본문이 명시한 공시일과 계약 대상 대조",
                                                                   verify_identity=True) for r in candidates))
                            matched = [d for d in matched if d]
                            incomplete = any(next((x.get("status") for x in history["items"]
                                if x["receipt_no"] == r["receipt_no"]), None) in
                                {"UNAVAILABLE", "LIMIT_REACHED", "PENDING"} for r in candidates)
                            if incomplete:
                                for doc in matched:
                                    record(doc["receipt_no"], status="AMBIGUOUS", reason="다른 후보의 원문을 확인하지 못해 연결을 보류했습니다.")
                                limit("후보 중 일부 원문을 확보하지 못해 원공시를 확정하지 않았습니다.")
                            elif len(matched) == 1:
                                doc = matched[0]
                                if not original and original_reference(doc["report_name"], ref["source"]["quote"]):
                                    doc["history_role"] = "ORIGINAL"
                                    record(doc["receipt_no"], role="ORIGINAL")
                                accept(doc)
                            elif len(matched) > 1:
                                for doc in matched:
                                    record(doc["receipt_no"], status="AMBIGUOUS", reason="같은 계약으로 볼 수 있는 후보가 여러 개여서 연결하지 않았습니다.")
                                limit("원공시 후보가 여러 개여서 임의로 선택하지 않았습니다.")
                            else:
                                limit("본문 공시일의 후보에서 동일 계약의 원문을 확인하지 못했습니다.")
                    # 별도 신규공시에서 원계약을 찾은 경우 그 원공시의 연결 이력도 확인합니다.
                    roots = [r for r in history["items"] if r.get("role") == "ORIGINAL"
                             and r.get("status") == "ACQUIRED" and r["receipt_no"] not in targets]
                    for root in roots[:1]:
                        origin = root["receipt_no"]
                        linked = await call("history_family", {"receipt_no": origin})
                        expected = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={origin}"
                        if (linked.get("source_url") != expected or not any(
                                r.get("receipt_no") == origin for r in linked.get("items", []))):
                            limit("확보한 원공시의 후속 연결 목록은 확인하지 못했습니다.")
                            continue
                        related = [{**r, "relation_url": expected} for r in linked["items"] if
                                   re.fullmatch(r"[0-9]{14}", r.get("receipt_no", ""))
                                   and origin < r["receipt_no"] < current
                                   and r.get("filed_at", "").replace("-", "") == r["receipt_no"][:8]]
                        related.sort(key=lambda r: r["receipt_no"])
                        history["candidates"] = list({r["receipt_no"]: r for r in
                                                      [*history["candidates"], *related[-19:]]}.values())
                        if related and not requested_receipt:
                            doc = await fetch(related[-1], "PREVIOUS", "본문으로 확인한 원공시의 DART 연결 이력")
                            if doc:
                                accept(doc)
        except RunCancelled:
            raise
        except TimeoutError:
            limit("과거 공시 조회 시간 한도에 도달해 확보된 자료만 사용합니다.")
        except Exception as error:
            limit("과거 공시 조회를 완료하지 못했습니다: " + type(error).__name__)
        finally:
            run.h.ledger.end_history(run.h.task_id)
            for row in history["items"]:
                if row.get("status") == "PENDING":
                    row.update(status="UNAVAILABLE", reason="원문 조회가 중단되거나 시간 한도에 도달했습니다.")
                elif row.get("status") == "FETCHED":
                    row.update(status="RELATION_UNCONFIRMED", reason="원문은 받았지만 동일 계약 여부의 대조를 완료하지 못했습니다.")
        if not any(r.get("role") == "ORIGINAL" and r.get("status") == "ACQUIRED" for r in history["items"]):
            limit("최초 공시 원문은 확인되지 않았습니다. 확보한 정정 이력을 최초 공시로 간주하지 않습니다.")
        history["status"] = "ACQUIRED" if documents else "UNAVAILABLE"
        if history["limitations"] and documents:
            history["status"] = "PARTIAL"
        run.h.history_data = copy.deepcopy(history)
        run.h.ledger.save_history(run.h.task_id, history)
        run.h.ledger.event(run.h.task_id, "HISTORY_RESULT", status=history["status"],
                           receipts=[r["receipt_no"] for r in history["items"] if r.get("status") == "ACQUIRED"])
        # 복구된 문서의 인용도 다시 구성합니다.
        for doc in documents.values():
            sources.extend(history_sources(doc))
        return {"history": history, "documents": list(documents.values()),
                "sources": validated_sources(sources, list(documents.values()), sources)}
