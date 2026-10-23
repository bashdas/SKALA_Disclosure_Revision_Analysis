import asyncio
import importlib.util
import json
import os
from pathlib import Path

import httpx
from app.config import Settings
from app.database import RagStore
from app.embedding import OpenAIEmbeddingService
from app.news_collector import NewsCollector
from app.news_store import NewsStore
from app.service import RagService

P = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("validated_naver_source", P / "backend/mcp/external-mcp/app/naver_news.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
D = Path(__file__).parent


async def main():
    settings = Settings(database_url=os.environ["NEWS_TEST_DATABASE_URL"])
    store = RagStore(settings.database_url)
    class Sources:
        def __init__(self):
            self.naver = module.NaverNews()
        async def news_headlines(self, company):
            return await self.naver.headlines(company)
    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        embedding = OpenAIEmbeddingService(client, settings.openai_api_key.get_secret_value(), settings.rag_embedding_model)
        service = RagService(Sources(), embedding, store, settings)
        collector = NewsCollector(service, client, settings)
        targets = json.loads(os.environ["VALIDATION_FAVORITES"])
        collector.store.targets = lambda: targets
        original = collector.classifier
        classifications = []
        async def record(rows, favorites):
            tags = await original(rows, favorites)
            classifications.extend([{**row, **tag.model_dump()} for row, tag in zip(rows, sorted(tags, key=lambda x: x.index), strict=True)])
            (D / "live-classifications.json").write_text(json.dumps(classifications, ensure_ascii=False, indent=2))
            print("classified", len(classifications), flush=True)
            return tags
        collector.classifier = record
        result = await collector.run_once(force=True)
        (D / "live-collection.json").write_text(json.dumps({"real_model": True, "real_naver_requests": True,
            "favorites": targets, "model": settings.news_classification_model,
            "retention_days": settings.news_retention_days, "interval_seconds": settings.news_collection_interval_seconds,
            "result": result, "collection": NewsStore(store).status()}, ensure_ascii=False, indent=2))
        print(json.dumps(result), flush=True)
    store.engine.dispose()


asyncio.run(main())
