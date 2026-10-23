"""시황 수집 운영 명령입니다. 기본 정리는 미리보기입니다."""

import argparse
import asyncio
import json
from datetime import datetime, timezone

import httpx

from app.config import Settings
from app.database import RagStore
from app.embedding import OpenAIEmbeddingService
from app.news_collector import NewsCollector
from app.news_store import NewsStore
from app.service import RagService
from app.upstream import McpSources


async def main():
    parser = argparse.ArgumentParser(description="시황 수집 운영")
    parser.add_argument("action", choices=["status", "collect", "retry", "cleanup"])
    parser.add_argument(
        "--apply", action="store_true", help="정리 미리보기의 삭제를 실행합니다."
    )
    args = parser.parse_args()
    settings = Settings()
    store = RagStore(settings.database_url)
    try:
        news = NewsStore(store)
        if args.action == "status":
            print(
                json.dumps(
                    {
                        **news.status(),
                        "collection_enabled": settings.news_collection_enabled,
                        "usage_authorized": bool(
                            settings.news_usage_authorization.strip()
                        ),
                    },
                    ensure_ascii=False,
                )
            )
            return
        if args.action == "cleanup":
            with news.collection_lock() as acquired:
                result = (
                    news.cleanup(datetime.now(timezone.utc), settings, not args.apply)
                    if acquired
                    else {"status": "BUSY"}
                )
            print(json.dumps(result, ensure_ascii=False))
            return
        async with httpx.AsyncClient(
            timeout=settings.rag_mcp_request_timeout_seconds, trust_env=False
        ) as client:
            sources = McpSources(
                client,
                settings.business_mcp_url,
                settings.external_mcp_url,
                settings.rag_mcp_request_timeout_seconds,
            )
            embedding = OpenAIEmbeddingService(
                client,
                settings.openai_api_key.get_secret_value(),
                settings.rag_embedding_model,
            )
            collector = NewsCollector(
                RagService(sources, embedding, store, settings), client, settings
            )
            result = await collector.run_once(
                force=True, retry_only=args.action == "retry"
            )
            print(json.dumps(result, ensure_ascii=False))
    finally:
        store.engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
