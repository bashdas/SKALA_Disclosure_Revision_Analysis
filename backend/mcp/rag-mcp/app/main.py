import asyncio
import json
from contextlib import asynccontextmanager, suppress
from typing import Annotated, Literal
from uuid import UUID

import httpx
from disclosure_shared.health import HealthResponse
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field

from app.config import Settings
from app.database import RagStore
from app.embedding import OpenAIEmbeddingService
from app.errors import RagError
from app.news_collector import NewsCollector
from app.service import RagService
from app.upstream import McpSources


def create_app(settings=None, *, sources=None, embedding=None, store=None):
    settings = settings or Settings()
    mcp = FastMCP("rag-mcp", stateless_http=True, json_response=True, streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=settings.mcp_allowed_hosts))

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(timeout=settings.rag_mcp_request_timeout_seconds, follow_redirects=False, trust_env=False) as client:
            storage = store or (RagStore(settings.database_url) if settings.database_url else None)
            upstream = sources or McpSources(client, settings.business_mcp_url, settings.external_mcp_url, settings.rag_mcp_request_timeout_seconds)
            provider = embedding or OpenAIEmbeddingService(client, settings.openai_api_key.get_secret_value(), settings.rag_embedding_model)
            app.state.service = RagService(upstream, provider, storage, settings)
            collector_task = None
            if storage is not None and settings.news_collection_enabled:
                app.state.news_collector = NewsCollector(app.state.service, client, settings)
                collector_task = asyncio.create_task(app.state.news_collector.run())
            try:
                async with mcp.session_manager.run():
                    yield
            finally:
                if collector_task:
                    collector_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await collector_task
                if store is None and storage is not None:
                    storage.engine.dispose()

    app = FastAPI(title="RAG MCP", lifespan=lifespan)
    app.state.mcp = mcp

    async def invoke(method, *args):
        if app.state.service.store is None:
            raise ToolError('{"code":"RAG_UNAVAILABLE","message":"Database is not configured"}')
        try:
            return await getattr(app.state.service, method)(*args)
        except RagError as error:
            raise ToolError(json.dumps({"code": error.code, "message": error.message})) from None
        except Exception:
            raise ToolError('{"code":"RAG_OPERATION_FAILED","message":"RAG operation failed"}') from None

    @mcp.tool()
    async def ensure_analysis_index(task_id: UUID) -> dict:
        """Fetch fixed Memo and disclosure through MCP, then prepare their vector index."""
        return await invoke("ensure_analysis_index", task_id)

    @mcp.tool()
    async def search_evidence(task_id: UUID, query: Annotated[str, Field(min_length=1, max_length=2000, pattern=r"\S")],
        top_k: Annotated[int, Field(ge=1, le=20)] = 5,
        document_types: list[Literal["MEMO", "DISCLOSURE"]] | None = None) -> dict:
        """Search this task's indexed documents. Higher normalized cosine scores are better."""
        return await invoke("search_evidence", task_id, query, top_k, document_types)

    @mcp.tool()
    async def search_market_news(task_id: UUID,
        query: Annotated[str, Field(min_length=1, max_length=2000)],
        top_k: Annotated[int, Field(ge=1, le=12)] = 6) -> dict:
        """분석 요청 시각 이전의 기업 및 공통 시황 제목을 의미 검색합니다. 본문 확인은 별도입니다."""
        return await invoke("search_market_news", task_id, query, top_k)

    @mcp.tool()
    async def read_market_news(task_id: UUID,
        article_ids: Annotated[list[UUID], Field(min_length=1, max_length=3)]) -> dict:
        """저장된 관련 기사 식별자만 받아 네이버 링크의 본문과 시각을 검증합니다."""
        return await invoke("read_market_news", task_id, article_ids)

    @app.get("/health", response_model=HealthResponse)
    async def health():
        return HealthResponse(service="rag-mcp")

    app.mount("/", mcp.streamable_http_app())
    return app


app = create_app()
