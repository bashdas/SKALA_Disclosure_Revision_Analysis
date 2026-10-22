import asyncio

import pytest

from disclosure_ai.workflow.reporting import compose
from disclosure_ai.workflow.shared import requests


@pytest.mark.parametrize("kind,query", [
    ("NEW", "삼성중공업 2026년 3분기 실적 발표 현금흐름"),
    ("CORRECTION", "삼성중공업 선박 계약 해지 선수금 비용 회수"),
])
def test_external_query_preserves_agent_context(kind, query):
    state = {"request": {"disclosure_receipt_no": "20261015800457"},
             "filing": {"analysis_type": kind}, "jobs": {"FINANCE": {
                 "status": "NEEDS_TOOLS", "requests": [{"tool": "academic", "query": query}]}}}
    result = asyncio.run(requests(None, state))
    assert result["lookups"][0]["args"]["query"] == query


def test_all_perspective_decisions_share_report_section():
    data = {"request": {"company_name_snapshot": "삼성중공업", "disclosure_receipt_no": "20261015800457"},
            "base": {"proposals": [], "selected": [{"perspective_type": "FINANCE", "selection_reason": "현금흐름 확인"}],
                     "not_selected": [{"perspective_type": "INDUSTRY_CONTRACT", "reason": "계약 영향 없음"},
                                      {"perspective_type": "FX_HEDGE", "reason": "환율 영향 없음"}]},
            "results": {}, "warnings": []}
    content = compose(data)["content"]
    table = content.split("## 관점 선택과 이유")[1].split("## ")[0]
    for reason in ["현금흐름 확인", "계약 영향 없음", "환율 영향 없음"]:
        assert reason in table
    assert "추가 분석을 선택하지 않은 이유" not in content
