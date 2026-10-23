import asyncio
import copy
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from test_analysis import FakeTools, fake_model, initial, ledger  # noqa: F401

from disclosure_ai.harness.ledger import Ledger
from disclosure_ai.harness.runtime import Harness
from disclosure_ai.services.documents import model_context
from disclosure_ai.services.history import acquire
from disclosure_ai.workflow.graph import AnalysisGraph
from disclosure_ai.workflow.reporting import emergency
from disclosure_ai.workflow.shared import lookup, publish

CURRENT = "20251229800710"
ORIGINAL = "20230228000001"
PREVIOUS = "20241015000002"
CORP = "00398701"
CURRENT_TEXT = "계약상대방 Tesla\n제품명 NCMA 양극재\n공급 물량 변경에 따라 계약금액을 변경합니다."
OLD_TEXT = "계약상대방 Tesla\n제품명 NCMA 양극재\n계약금액 100\n계약기간 2024년부터 2025년까지\n인도 조건은 개별 발주에 따릅니다."


def filing(receipt=CURRENT, text=CURRENT_TEXT, correction=False, corp=CORP):
    return {"documents": [{"document_id": "filing:" + receipt, "text": text,
                "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}",
                "published_at": f"{receipt[:4]}-{receipt[4:6]}-{receipt[6:8]}"}],
            "changes": [], "complete_correction_table": False, "corp_code": corp,
            "report_name": "[기재정정]공급계약" if correction else "투자판단관련주요경영사항",
            "metadata_status": "FOUND", "filed_at": f"{receipt[:4]}-{receipt[4:6]}-{receipt[6:8]}"}


def row(receipt, correction=False, corp=CORP):
    return {"receipt_no": receipt, "is_correction": correction, "corp_code": corp,
            "filed_at": f"{receipt[:4]}-{receipt[4:6]}-{receipt[6:8]}",
            "report_name": "[기재정정]공급계약" if correction else "공급계약"}


def state(correction=False, text=CURRENT_TEXT):
    value = initial()
    value["request"].update(disclosure_receipt_no=CURRENT, corp_code=CORP,
                            disclosure_type="CORRECTION" if correction else "NEW")
    value.update(filing={**filing(text=text, correction=correction),
                         "analysis_type": "CORRECTION" if correction else "NEW"},
                 memo={"document_id": "memo:1", "text": "Tesla 계약의 물량 확대를 성장 가정으로 봅니다.", "version": 1},
                 documents=[], context=[])
    value["documents"] = [*value["filing"]["documents"], value["memo"]]
    return value


def request(value, target=None):
    doc = value["filing"]["documents"][0]
    return {"reason": "기존 계약의 대상과 물량을 대조합니다.", "receipt_no": target,
            "evidence": [{"document_id": doc["document_id"], "location": "line:1", "quote": doc["text"]}]}


class Tools(FakeTools):
    def __init__(self, *, family=None, docs=None, search=None, delay=0):
        super().__init__()
        self.family = family if family is not None else [row(ORIGINAL), row(PREVIOUS, True), row(CURRENT, True)]
        self.docs = docs or {ORIGINAL: filing(ORIGINAL, OLD_TEXT), PREVIOUS: filing(PREVIOUS, OLD_TEXT, True)}
        self.search = search or []
        self.history_calls = []
        self.delay = delay
        self.active = self.maximum = 0

    async def call(self, name, args):
        if name.startswith("history_"):
            self.history_calls.append((name, copy.deepcopy(args)))
        if name == "history_family":
            return {"items": self.family, "source_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={CURRENT}"}
        if name == "history_search":
            assert args["corp_code"] == CORP
            assert args["start_date"] == args["end_date"]
            return {"items": self.search, "has_more": False}
        if name == "history_document":
            self.active += 1
            self.maximum = max(self.maximum, self.active)
            try:
                if self.delay:
                    await asyncio.sleep(self.delay)
                return copy.deepcopy(self.docs.get(args["receipt_no"], {"error": "MISSING"}))
            finally:
                self.active -= 1
        return await super().call(name, args)


def run(book, tools):
    return SimpleNamespace(h=Harness("task", book, fake_model), tools=tools)


def merge(value, result):
    docs = {d["document_id"]: d for d in [*value["documents"], *result["documents"]]}
    return {**value, "documents": list(docs.values()), "context": [*value["context"], *result["sources"]],
            "history": result["history"]}


def test_auto_original_and_previous_are_available_before_base_without_changing_current(ledger):  # noqa: F811
    tools = Tools(delay=0.01)
    data = state(True)

    async def check():
        runner = run(ledger, tools)
        result = await acquire(runner, data, automatic=True)
        assert tools.maximum == 2
        assert len(result["documents"]) == 2
        assert {r["role"] for r in result["history"]["items"]} == {"ORIGINAL", "PREVIOUS"}
        data_with_history = merge(data, result)
        context = model_context(data["filing"], result["sources"], data["memo"], result["history"])
        assert {s["receipt_no"] for s in context["history_context"]} == {ORIGINAL, PREVIOUS}
        assert not context["context"]  # 과거 문서를 현재 정정표에 합치지 않습니다.
        report = emergency(runner, data_with_history, TimeoutError())
        assert "최초 공시 " + ORIGINAL in report["content"]
        assert report["report_json"]["disclosure_history"]["items"][0]["evidence"]
        assert data["filing"]["changes"] == []
        again = await acquire(runner, data, automatic=True)
        assert len(again["documents"]) == 2
        assert len([n for n, _ in tools.history_calls if n == "history_document"]) == 2

    asyncio.run(check())


def test_single_predecessor_is_fetched_once_and_future_is_excluded(ledger):  # noqa: F811
    tools = Tools(family=[row(ORIGINAL), row(CURRENT, True), row("20261022000001", True)])

    async def check():
        result = await acquire(run(ledger, tools), state(True), automatic=True)
        assert len(result["documents"]) == 1
        assert result["history"]["items"][0]["role"] == "ORIGINAL"
        assert [args["receipt_no"] for n, args in tools.history_calls if n == "history_document"] == [ORIGINAL]

    asyncio.run(check())


def test_new_disclosure_requests_history_then_reanalyses_once(ledger):  # noqa: F811
    tools = Tools()
    data = state(False)
    calls = []
    original_call = tools.call

    async def call(name, args):
        if name == "disclosure_get_document":
            return data["filing"]
        if name == "business_get_memo":
            return data["memo"]
        return await original_call(name, args)

    tools.call = call

    async def model(role, context, schema):
        answer = await fake_model(role, context, schema)
        if role == "base":
            calls.append(context)
            assert context["analysis_type"] == "NEW"
            answer["history_request"] = request(data) if context["history_lookup_allowed"] else None
            if not context["history_lookup_allowed"]:
                assert context["history_context"]
                old = {k: v for k, v in context["history_context"][0].items()
                       if k in {"document_id", "location", "quote", "url", "published_at"}}
                answer["history_comparisons"] = [{"receipt_no": ORIGINAL, "subject": "계약 범위",
                    "past_fact": "과거 계약금액은 100입니다.", "current_fact": "공급 물량이 변경됐습니다.",
                    "interpretation": "동일 물량에 대한 변경인지 추가 확인해야 합니다.",
                    "evidence": [old, request(data)["evidence"][0]]}]
        return answer

    async def check():
        graph = AnalysisGraph(Harness("task", ledger, model), tools, InMemorySaver()).graph
        result = await graph.ainvoke({"request": data["request"], "scope": "org", "warnings": [], "results": {}},
                                    {"configurable": {"thread_id": "new-history"}})
        assert len(calls) == 2
        report = result["report"]["report_json"]
        assert report["analysis_type"] == "NEW"
        assert not report["corrections"]
        assert report["disclosure_history"]["status"] == "ACQUIRED"
        assert report["disclosure_history"]["comparisons"][0]["evidence"]
        assert "비교 항목: 계약 범위" in result["report"]["content"]
        assert "조회한 과거 공시" in result["report"]["content"]
        assert ledger.row("task")["turns"] == 4

    asyncio.run(check())


@pytest.mark.parametrize("text", [
    f"최초 공시 접수번호 {ORIGINAL}\n계약상대방 Tesla",
    f"원공시 https://dart.fss.or.kr/dsaf001/main.do?rcpNo={ORIGINAL}\n계약상대방 Tesla",
    "최초 공시일 2023년 2월 28일\n계약상대방 Tesla",
])
def test_explicit_number_link_and_date_work_outside_family(ledger, text):  # noqa: F811
    data = state(text=text)
    tools = Tools(family=[row(CURRENT)], search=[row(ORIGINAL)])

    async def check():
        result = await acquire(run(ledger, tools), data, request(data))
        assert len(result["documents"]) == 1
        item = result["history"]["items"][0]
        assert item["receipt_no"] == ORIGINAL and item["status"] == "ACQUIRED"
        assert item["relation_evidence"][0]["document_id"] == "filing:" + CURRENT

    asyncio.run(check())


@pytest.mark.parametrize("mode", ["ambiguous", "wrong_company", "wrong_contract", "unavailable_candidate"])
def test_date_candidates_are_not_linked_by_title_alone(ledger, mode):  # noqa: F811
    second = "20230228000002"
    docs = {ORIGINAL: filing(ORIGINAL, OLD_TEXT)}
    candidates = [row(ORIGINAL)]
    if mode in {"ambiguous", "unavailable_candidate"}:
        candidates.append(row(second))
        if mode == "ambiguous":
            docs[second] = filing(second, OLD_TEXT)
    if mode == "wrong_company":
        docs[ORIGINAL] = filing(ORIGINAL, OLD_TEXT, corp="00126380")
    if mode == "wrong_contract":
        docs[ORIGINAL] = filing(ORIGINAL, "계약상대방 Samsung\n제품명 반도체\n공급계약")
    tools = Tools(family=[row(CURRENT)], search=candidates, docs=docs)
    data = state(text="최초 공시일 2023-02-28\n계약상대방 Tesla\n제품명 NCMA 양극재")

    async def check():
        result = await acquire(run(ledger, tools), data, request(data))
        assert not result["documents"]
        assert result["history"]["limitations"]
        assert not result["sources"]

    asyncio.run(check())


def test_only_corrections_are_never_labelled_original(ledger):  # noqa: F811
    tools = Tools(family=[row(PREVIOUS, True), row(CURRENT, True)])

    async def check():
        result = await acquire(run(ledger, tools), state(True), automatic=True)
        assert result["history"]["items"][0]["role"] == "PREVIOUS"
        assert any("최초 공시 원문은 확인되지" in t for t in result["history"]["limitations"])

    asyncio.run(check())


def test_history_budget_and_unique_receipts_survive_restart(ledger, tmp_path):  # noqa: F811
    third, fourth = "20240401000003", "20240501000004"
    tools = Tools(family=[row(ORIGINAL), row(third, True), row(fourth, True), row(PREVIOUS, True), row(CURRENT, True)],
                  docs={ORIGINAL: filing(ORIGINAL, OLD_TEXT), PREVIOUS: filing(PREVIOUS, OLD_TEXT, True),
                        third: filing(third, OLD_TEXT, True), fourth: filing(fourth, OLD_TEXT, True)})

    async def check():
        data = state(True)
        result = await acquire(run(ledger, tools), data, automatic=True)
        data = merge(data, result)
        # 새 Harness에서도 SQLite의 사용량과 조회 캐시를 재사용합니다.
        reopened = Ledger(str(ledger.path))
        runner = run(reopened, tools)
        try:
            result = await acquire(runner, data, request(data, third))
            data = merge(data, result)
            result = await acquire(runner, data, request(data, fourth))
            assert len(reopened.history_receipts("task")) == 3
            assert len([x for x in tools.history_calls if x[0] == "history_document"]) == 3
            assert any("3건" in x for x in result["history"]["limitations"])
            reopened.db.execute("UPDATE history_budget SET elapsed=30 WHERE run_id='task'")
            reopened.db.commit()
            count = len(tools.history_calls)
            result = await acquire(runner, data, request(data, fourth))
            assert len(tools.history_calls) == count
            assert result["documents"]  # 이미 확보한 원문은 보존합니다.
        finally:
            reopened.db.close()

    asyncio.run(check())


def test_history_lookup_failure_and_invalid_request_do_not_abort(ledger):  # noqa: F811
    tools = Tools(family=[row(CURRENT)])
    data = state()

    async def check():
        runner = run(ledger, tools)
        bad = request(data)
        bad["evidence"][0]["quote"] = "현재 공시에 없는 참조"
        result = await acquire(runner, data, bad)
        assert not tools.history_calls
        assert result["history"]["limitations"]
        result = await acquire(runner, data, request(data))
        assert result["history"]["status"] == "UNAVAILABLE"
        assert not result["documents"]

    asyncio.run(check())


def test_shared_search_combines_rag_with_historical_documents(ledger):  # noqa: F811
    tools = Tools()

    async def check():
        runner = run(ledger, tools)
        data = state(True)
        data = merge(data, await acquire(runner, data, automatic=True))
        data.update(lookups=[{"kind": "FINANCE", "tool": "search_evidence", "args": {"task_id": "task", "query": "계약금액"}}],
                    jobs={"FINANCE": {"status": "NEEDS_TOOLS", "selection": {"perspective_type": "FINANCE"}}})
        result = await lookup(runner, data)
        assert any(s["document_id"] == "filing:" + ORIGINAL for s in result["lookup_results"][0]["response"]["sources"])
        data.update(result)
        result = await publish(runner, data)
        assert result["jobs"]["FINANCE"]["status"] == "PENDING"
        assert result["history"]["items"]
        assert result["context"]

    asyncio.run(check())


def test_public_contract_amendment_without_counterparty_in_current_text(ledger):  # noqa: F811
    text = ("단일판매ㆍ공급계약체결 공시 내용 정정(계약금액 변경)\n"
            "하이니켈 양극재 공급 계약 체결에 대한 내용입니다.\n"
            "※ 관련공시 2023-02-28 단일판매ㆍ공급계약체결")
    contract = {**row(ORIGINAL), "report_name": "단일판매ㆍ공급계약체결"}
    unrelated = {**row("20230228000002"), "report_name": "주주총회소집결의"}
    old = filing(ORIGINAL, "판매ㆍ공급계약 내용 하이니켈 양극재 공급 계약 체결\n계약상대방 Tesla\n계약금액 100")
    old["report_name"] = contract["report_name"]
    tools = Tools(family=[row(CURRENT)], search=[unrelated, contract], docs={ORIGINAL: old})
    value = state(text=text)

    async def check():
        result = await acquire(run(ledger, tools), value, request(value))
        assert len(result["documents"]) == 1
        assert result["history"]["items"][0]["role"] == "ORIGINAL"
        assert len([name for name, _ in tools.history_calls if name == "history_document"]) == 1

    asyncio.run(check())


def test_completed_predecessor_is_preserved_when_other_lookup_times_out(ledger):  # noqa: F811
    class SlowTools(Tools):
        async def call(self, name, args):
            if name == "history_document" and args["receipt_no"] == PREVIOUS:
                await asyncio.sleep(0.2)
            return await super().call(name, args)

    async def check():
        ledger.begin_history("task")
        ledger.end_history("task")
        ledger.db.execute("UPDATE history_budget SET elapsed=29.95 WHERE run_id='task'")
        ledger.db.commit()
        result = await acquire(run(ledger, SlowTools()), state(True), automatic=True)
        assert len(result["documents"]) == 1
        assert result["documents"][0]["receipt_no"] == ORIGINAL
        assert result["history"]["status"] == "PARTIAL"
        assert any("시간 한도" in text for text in result["history"]["limitations"])
        assert ledger.db.execute("SELECT started FROM history_budget").fetchone()[0] is None

    asyncio.run(check())


def test_perspective_can_request_history_and_receive_documents_without_losing_state(ledger):  # noqa: F811
    tools = Tools()
    data = state()
    lookup_request = {"kind": "FINANCE", "tool": "disclosure_history", "args": request(data)}
    data.update(lookups=[lookup_request], jobs={"FINANCE": {"status": "NEEDS_TOOLS",
        "selection": {"perspective_type": "FINANCE"}}})

    async def check():
        runner = run(ledger, tools)
        response = await lookup(runner, data)
        data.update(response)
        result = await publish(runner, data)
        assert any(d.get("history_role") == "ORIGINAL" for d in result["documents"])
        assert result["jobs"]["FINANCE"]["status"] == "PENDING"
        assert result["history"]["items"]
        assert "documents" not in result["jobs"]["FINANCE"]["observations"][0]["result"]

    asyncio.run(check())


def test_automatic_history_is_in_graph_base_context(ledger):  # noqa: F811
    tools = Tools()
    data = state(True)
    delegate = tools.call
    seen = []

    async def call(name, args):
        if name == "disclosure_get_document":
            return data["filing"]
        if name == "business_get_memo":
            return data["memo"]
        return await delegate(name, args)

    tools.call = call

    async def model(role, context, schema):
        if role == "base":
            seen.append(context)
            assert context["history_context"]
            assert context["analysis_type"] == "CORRECTION"
        return await fake_model(role, context, schema)

    async def check():
        graph = AnalysisGraph(Harness("task", ledger, model), tools, InMemorySaver()).graph
        result = await graph.ainvoke({"request": data["request"], "scope": "org", "warnings": [], "results": {}},
                                    {"configurable": {"thread_id": "auto-history"}})
        assert len(seen) == 1
        assert result["report"]["report_json"]["disclosure_history"]["status"] == "ACQUIRED"
        assert not result["report"]["report_json"]["corrections"]

    asyncio.run(check())


def test_mcp_adapter_reuses_existing_server_tools(monkeypatch):
    from hashlib import sha256

    from disclosure_ai.services import tools as adapter

    calls = []

    async def mcp(service, name, args):
        calls.append((service, name, args))
        if name == "get_disclosure":
            text = "계약 원문"
            return {"receipt_no": ORIGINAL, "document": {"text": text,
                "content_hash": sha256(text.encode()).hexdigest(), "tables": [], "blocks": [], "files": []},
                "source": {"original_location": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={ORIGINAL}"}}
        return {"items": []}

    monkeypatch.setattr(adapter, "mcp_call", mcp)

    async def check():
        client = adapter.Tools("")
        await client.call("history_family", {"receipt_no": CURRENT})
        await client.call("history_search", {"corp_code": CORP, "start_date": "2023-02-28", "end_date": "2023-02-28"})
        result = await client.call("history_document", {"receipt_no": ORIGINAL})
        assert result["documents"][0]["text"] == "계약 원문"
        assert [name for _, name, _ in calls] == ["opendart_get_disclosure_family", "opendart_search_disclosures", "get_disclosure"]
        assert all(service == "EXTERNAL" for service, _, _ in calls)

    asyncio.run(check())


def test_explicit_original_can_discover_its_own_previous_correction(ledger):  # noqa: F811
    class SeparateTools(Tools):
        async def call(self, name, args):
            if name == "history_family" and args["receipt_no"] == ORIGINAL:
                self.history_calls.append((name, args))
                return {"items": [row(ORIGINAL), row(PREVIOUS, True)],
                        "source_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={ORIGINAL}"}
            return await super().call(name, args)

    tools = SeparateTools(family=[row(CURRENT)])
    value = state(text=f"원공시 접수번호 {ORIGINAL}\n계약상대방 Tesla")

    async def check():
        result = await acquire(run(ledger, tools), value, request(value))
        assert {d["receipt_no"] for d in result["documents"]} == {ORIGINAL, PREVIOUS}
        assert {r["role"] for r in result["history"]["items"]} == {"ORIGINAL", "PREVIOUS"}

    asyncio.run(check())


def test_accepted_original_is_recovered_without_checkpoint_or_remaining_budget(ledger):  # noqa: F811
    tools = Tools()
    data = state(True)

    async def check():
        await acquire(run(ledger, tools), data, automatic=True)
        ledger.db.execute("UPDATE history_budget SET elapsed=30 WHERE run_id='task'")
        ledger.db.commit()
        reopened = Ledger(str(ledger.path))
        runner = run(reopened, tools)
        try:
            before = len(tools.history_calls)
            result = await acquire(runner, data, automatic=True)
            assert len(result["documents"]) == 2
            assert len(tools.history_calls) == before
            # 상위 그래프가 수집 결과를 아직 체크포인트에 기록하지 못한 경우도 복구합니다.
            body = emergency(runner, data, TimeoutError())
            assert ORIGINAL in body["content"] and PREVIOUS in body["content"]
            assert any(ORIGINAL in s["document_id"] for s in body["report_json"]["sources"])
            assert reopened.history_receipts("task") == [ORIGINAL, PREVIOUS]
        finally:
            reopened.db.close()

    asyncio.run(check())


def test_agent_can_follow_contract_reference_after_automatic_amendment_family(ledger):  # noqa: F811
    termination = "20240401000003"
    text = "계약상대방 Tesla\n이번 계약 해지 공시의 내용이 변경됐습니다.\n※ 관련공시 2023-02-28 공급계약"
    tools = Tools(family=[row(termination), row(PREVIOUS, True), row(CURRENT, True)],
                  search=[row(ORIGINAL)], docs={termination: filing(termination, OLD_TEXT),
                  PREVIOUS: filing(PREVIOUS, OLD_TEXT, True), ORIGINAL: filing(ORIGINAL, OLD_TEXT)})
    value = state(True, text)

    async def check():
        runner = run(ledger, tools)
        first = await acquire(runner, value, automatic=True)
        assert {d["receipt_no"] for d in first["documents"]} == {termination, PREVIOUS}
        data = merge(value, first)
        result = await acquire(runner, data, request(data))
        assert {d["receipt_no"] for d in result["documents"]} == {ORIGINAL, termination, PREVIOUS}

    asyncio.run(check())


def test_financial_amounts_and_delivery_dates_are_not_explicit_filing_references():
    from disclosure_ai.services.history import explicit_references

    value = filing(text="단일판매 공급계약 공시\n계약금액 20230228900155원\n계약기간 시작일 2023-02-28")
    assert explicit_references(value, CURRENT) == []


def test_required_assessment_runs_history_even_without_separate_request(ledger):  # noqa: F811
    tools = Tools()
    data = state()
    delegate = tools.call
    seen = []

    async def call(name, args):
        if name == "disclosure_get_document":
            return data["filing"]
        if name == "business_get_memo":
            return data["memo"]
        return await delegate(name, args)

    tools.call = call

    async def model(role, context, schema):
        answer = await fake_model(role, context, schema)
        if role == "base":
            seen.append(context)
            answer["history_assessment"] = {"status": "REQUIRED" if context["history_lookup_allowed"] else "ALREADY_AVAILABLE",
                "reason": "원래 계약의 물량과 조건이 기존 성장 가정의 검토에 필요합니다.",
                "evidence": request(data)["evidence"]}
        return answer

    async def check():
        graph = AnalysisGraph(Harness("task", ledger, model), tools, InMemorySaver()).graph
        result = await graph.ainvoke({"request": data["request"], "scope": "org", "warnings": [], "results": {}},
                                    {"configurable": {"thread_id": "assessment"}})
        assert len(seen) == 2
        assert result["history"]["status"] == "ACQUIRED"

    asyncio.run(check())


def test_boilerplate_counterparty_fields_do_not_establish_contract_identity(ledger):  # noqa: F811
    value = state(text="최초 공시일 2023-02-28\n계약상대방의 최근매출액 100\n계약상대방 변경없음")
    old = filing(ORIGINAL, "계약상대방 Samsung\n계약상대방의 최근매출액 100\n계약상대방 변경없음")
    tools = Tools(family=[row(CURRENT)], search=[row(ORIGINAL)], docs={ORIGINAL: old})

    async def check():
        result = await acquire(run(ledger, tools), value, request(value))
        assert not result["documents"]

    asyncio.run(check())


def test_ungrounded_model_receipt_does_not_block_verified_date_reference(ledger):  # noqa: F811
    value = state(text="최초 공시일 2023-02-28\n계약상대방 Tesla")
    tools = Tools(family=[row(CURRENT)], search=[row(ORIGINAL)])

    async def check():
        result = await acquire(run(ledger, tools), value, request(value, "20230228999999"))
        assert {d["receipt_no"] for d in result["documents"]} == {ORIGINAL}
        assert not any(args.get("receipt_no") == "20230228999999" for _, args in tools.history_calls)
        assert any("사용하지 않고" in text for text in result["history"]["notes"])

    asyncio.run(check())


def test_comparison_facts_are_checked_even_when_legacy_analysis_is_advisory(ledger):  # noqa: F811
    unsafe = "이번 공시는 계약기간을 바꾸지 않았습니다."

    async def model(role, context, schema):
        assert role == "output_check"
        return {"safe_indices": [row["index"] for row in context["sentences"] if row["text"] != unsafe]}

    async def check():
        harness = Harness("task", ledger, model)
        payload = {"history_comparisons": [{"receipt_no": ORIGINAL, "subject": "계약기간",
            "past_fact": "기존 계약기간은 2025년까지입니다.", "current_fact": unsafe,
            "interpretation": "이번 공시에서 기간 변경 여부는 확인하지 못했습니다.",
            "evidence": [{"document_id": "current", "location": "line:1", "quote": "물량 변경"}]}],
            "reason": unsafe}
        result, warnings = await harness.review_output(payload, grounding=True, advisory=True)
        assert result["history_comparisons"][0]["current_fact"] == ""
        assert result["history_comparisons"][0]["past_fact"]
        assert result["reason"] == unsafe  # 기존 advisory 계약은 유지합니다.
        assert warnings

    asyncio.run(check())
