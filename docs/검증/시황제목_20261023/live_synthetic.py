"""합성 제목만 실제 모델에 전달합니다. 네이버 API와 기사 링크를 호출하지 않습니다."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx

from app.config import Settings
from app.news_collector import NewsCollector
from disclosure_ai.harness.ledger import Ledger
from disclosure_ai.harness.runtime import Harness
from disclosure_ai.workflow.perspectives import perspective


async def main():
    import os
    settings = Settings(news_usage_authorization="SYNTHETIC_TEST_ONLY", openai_api_key=os.environ["OPENAI_API_KEY"])
    # 외부 데이터와 기존 사용자 메모를 포함하지 않은 고정 합성 입력입니다.
    targets = [{"corp_code": "00111111", "company_name": "가상조선기업", "aliases": ["가상조선"], "industries": ["조선"]},
               {"corp_code": "00222222", "company_name": "가상지주기업", "aliases": ["가상"], "industries": ["지주"]}]
    headlines = ["가상조선기업과 가상지주기업, 합성 협력 계획 발표", "가상, 신규 투자 검토",
                 "기준금리 동결 보도, 추가 조정 가능성은 미정", "조선업 공급망 점검 회의 개최"]
    # NewsStore 생성이 필요 없는 순수 모델 분류 경로를 확인합니다.
    async with httpx.AsyncClient() as client:
        collector = object.__new__(NewsCollector)
        collector.settings, collector.client = settings, client
        tags = await collector.classify([{"title": h} for h in headlines], targets)
    cases = []
    for index, title in enumerate([headlines[2], "합성기업, 실적 발표 일정 안내"]):
        ledger = Ledger("/tmp/disclosure-web-validation/news-v2-live-" + str(uuid4()) + ".sqlite")
        task = str(uuid4()); ledger.begin(task, "synthetic-only")
        harness = Harness(task, ledger)
        source = {"document_id": "news:synthetic:" + str(index), "location": "news:title", "quote": title,
                  "url": "https://example.com/synthetic/" + str(index), "published_at": "2026-10-23T00:00:00+00:00"}
        memo = {"document_id": "memo:synthetic:v1", "text": "기존 가정은 금융비용이 현재 수준으로 유지된다는 것입니다. 금리 조정 가능성이 확인되면 금융비용 가정을 점검합니다."}
        filing = {"documents": [{"document_id": "filing:synthetic", "text": "합성 공시는 신규 자금조달 계획을 안내합니다."}], "changes": [], "analysis_type": "NEW"}
        state = {"selection": {"perspective_type": "MARKET_NEWS", "selection_reason": "합성 금리 가정 점검", "question": "보도 제목이 기존 가정의 어떤 점검 질문과 연결됩니까?"},
                 "request": {"company_name_snapshot": "합성기업", "disclosure_receipt_no": "20261023000000"},
                 "base": {"selected": []}, "context": [source], "memo": memo, "filing": filing,
                 "documents": [memo, *filing["documents"], {"document_id": source["document_id"], "text": title, "url": source["url"]}],
                 "jobs": {}, "market_news": {"articles": [{"title": title}], "title_only": True, "as_of": "2026-10-23T03:00:00Z"}}
        result = await perspective(SimpleNamespace(h=harness, tools=object()), state)
        cases.append({"input": state, "result": result, "events": ledger.events(task)})
        await harness.close(); ledger.db.close()
    output = {"real_model": True, "model": os.environ.get("OPENAI_MODEL", "gpt-5.4-mini"),
              "synthetic_titles_only": True, "naver_api_called": False,
              "classifications": [t.model_dump() for t in tags], "cases": cases}
    Path(__file__).with_name("live-synthetic-result.json").write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(json.dumps({"classified": len(tags), "perspectives": [c["result"]["results"]["MARKET_NEWS"]["status"] for c in cases]}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
