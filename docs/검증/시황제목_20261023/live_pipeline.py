"""전용 DB와 실제 분류 모델을 합성 뉴스로 검증합니다. 네이버에는 접속하지 않습니다."""
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
from sqlalchemy import select

from app.config import Settings
from app.database import RagStore
from app.news_collector import NewsCollector
from app.news_store import MarketNews
from app.service import RagService


async def main():
    url = os.environ["NEWS_TEST_DATABASE_URL"]
    assert "validation" in url.rsplit("/", 1)[-1]
    store = RagStore(url)
    now = datetime.now(timezone.utc)
    task = uuid4()
    targets = [{"corp_code": "00111111", "company_name": "가상조선기업"}, {"corp_code": "00222222", "company_name": "가상지주기업"}]
    titles = ["가상조선기업과 가상지주기업, 합성 협력 계획 발표", "가상, 신규 투자 검토", "기준금리 동결 보도, 추가 조정 가능성은 미정", "조선업 공급망 점검 회의 개최"]
    class Sources:
        async def news_search(self, query, start, display):
            return {"items": [{"title": title, "original_title": title, "url": "https://example.com/synthetic/" + str(i),
                               "original_url": None, "published_at": (now-timedelta(hours=1)).isoformat()} for i,title in enumerate(titles)],
                    "total": 4, "raw_count": 4}
        async def get_context(self, task_id):
            return {"task_id": str(task_id), "organization_id": str(uuid4()), "corp_code": targets[0]["corp_code"],
                    "company_name": targets[0]["company_name"], "created_at": datetime.now(timezone.utc).isoformat(),
                    "disclosure_receipt_no": "20261023000000", "memo": {"id": str(uuid4()), "version": 1, "content": "합성 메모"}}
    settings = Settings(news_usage_authorization="SYNTHETIC_TEST_ONLY", news_topics=["합성 금리"],
                        news_company_aliases={"00222222": ["가상"]},
                        news_company_industries={"00111111": ["조선"]}, openai_api_key=os.environ["OPENAI_API_KEY"])
    models = []
    async with httpx.AsyncClient() as client:
        service = RagService(Sources(), None, store, settings)
        collector = NewsCollector(service, client, settings)
        collector.store.targets = lambda: targets
        original = collector.classify
        async def record(rows, candidates):
            result = await original(rows, candidates)
            models.append({"rows": rows, "candidates": candidates, "response": [t.model_dump() for t in result]})
            return result
        collector.classifier = record
        result = await collector.run_once(force=True)
        with store.sessions() as session:
            rows = [collector.store.item(row) for row in session.scalars(select(MarketNews))]
        query = await service.search_market_news(task, "조선 공급망 금리", days=7)
        output = {"synthetic_titles_only": True, "real_model": True, "real_postgresql": True, "naver_api_called": False,
                  "collection": result, "models": models, "stored": rows, "rag_response": query}
        Path(__file__).with_name("live-pipeline-result.json").write_text(json.dumps(output, ensure_ascii=False, indent=2))
        print(json.dumps({"stored": len(rows), "scope_counts": {s:sum(r["scope"]==s for r in rows) for s in {r["scope"] for r in rows}},
                          "retrieved": len(query["articles"]), "body_fetched": False}))
    store.engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
