import hashlib
import json
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from app.chunking import Chunker
from app.embedding import validate_vectors
from app.errors import RagError
from app.news_store import NewsStore


class MemoContext(BaseModel):
    id: UUID
    version: int = Field(ge=1)
    content: str = Field(min_length=1)
    content_hash: str | None = None


class AnalysisContext(BaseModel):
    task_id: UUID
    organization_id: UUID
    memo: MemoContext
    corp_code: str | None = None
    company_name: str | None = None
    created_at: datetime | None = None
    disclosure_receipt_no: str = Field(pattern=r"^(?:[0-9]{14}|SEC:[0-9]{1,10}:[0-9]{10}-[0-9]{2}-[0-9]{6})$")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class RagService:
    def __init__(self, sources, embedding, store, settings):
        self.sources, self.embedding, self.store, self.settings = sources, embedding, store, settings
        self.chunker = Chunker(settings.rag_chunk_size, settings.rag_chunk_overlap)
        self.fingerprint = f"{settings.rag_embedding_model}:1536:{self.chunker.fingerprint}"

    async def context(self, task_id):
        try:
            context = AnalysisContext.model_validate(await self.sources.get_context(task_id))
            if context.task_id != task_id:
                raise ValueError("Task mismatch")
            return context
        except (ValidationError, ValueError, TypeError):
            raise RagError("INVALID_ANALYSIS_CONTEXT", "Business MCP returned an invalid context") from None

    async def db(self, method, *args):
        try:
            return await run_in_threadpool(method, *args)
        except Exception:
            raise RagError("RAG_DATABASE_FAILED", "RAG database operation failed") from None

    async def index_document(self, context, kind, identifier, version, text, source, document=None):
        identity = dict(organization_id=context.organization_id, document_type=kind, identifier=identifier,
            version=str(version), content_hash=digest([text, document, source.get("upstream_content_hash")]), fingerprint=self.fingerprint)
        cached = await self.db(self.store.find_document, identity)
        if cached:
            return cached
        chunks = self.chunker.split(text, document)
        vectors = validate_vectors(await self.embedding.embed([c.text for c in chunks]), len(chunks))
        return await self.db(self.store.save_document, identity, source, chunks, vectors)

    async def ensure_analysis_index(self, task_id):
        context = await self.context(task_id)
        disclosure = await self.sources.get_disclosure(context.disclosure_receipt_no)
        try:
            if disclosure["receipt_no"] != context.disclosure_receipt_no:
                raise ValueError("Receipt mismatch")
            document = disclosure["document"]
            if not isinstance(document["text"], str) or not document["text"].strip():
                raise ValueError("Missing text")
            source = {**disclosure["source"], "receipt_no": disclosure["receipt_no"],
                "corp_code": disclosure.get("corp_code"), "company_name": disclosure.get("company_name")}
            # Retrieval timestamps/ZIP packaging do not change the parsed document identity.
            document = {k: document[k] for k in ("text", "blocks", "tables") if k in document}
        except (KeyError, TypeError, ValueError):
            raise RagError("INVALID_DISCLOSURE", "External MCP returned an invalid disclosure") from None
        memo_source = {"provider": "BUSINESS_MCP", "identifier": str(context.memo.id),
            "memo_id": str(context.memo.id), "version": context.memo.version,
            "upstream_content_hash": context.memo.content_hash}
        memo = await self.index_document(context, "MEMO", str(context.memo.id), context.memo.version,
            context.memo.content, memo_source)
        filing = await self.index_document(context, "DISCLOSURE", disclosure["receipt_no"], "snapshot",
            document["text"], source, document)
        await self.db(self.store.link, task_id, context.organization_id, memo["id"], filing["id"])
        return {"task_id": str(task_id), "indexed": True, "memo_chunks": memo["chunks"],
            "disclosure_chunks": filing["chunks"], "sources": [memo["source"], filing["source"]]}

    async def search_evidence(self, task_id, query, top_k=5, document_types=None):
        context = await self.context(task_id)
        vector = validate_vectors(await self.embedding.embed([query]), 1)[0]
        results = await self.db(self.store.search, task_id, context.organization_id, context.memo.id,
            context.memo.version, context.disclosure_receipt_no, self.fingerprint, vector,
            ["MEMO", "DISCLOSURE"] if document_types is None else document_types,
            top_k, self.settings.rag_min_similarity)
        if results is None:
            raise RagError("INDEX_NOT_READY", "Run ensure_analysis_index for this task first")
        return {"query": query, "score_kind": "normalized_cosine_similarity_higher_is_better", "results": results}

    async def news_context(self, task_id):
        context = await self.context(task_id)
        if not context.created_at or context.created_at.tzinfo is None:
            raise RagError("NEWS_CUTOFF_UNAVAILABLE", "분석 요청 시각을 확인하지 못했습니다.")
        return context

    async def search_market_news(self, task_id, query, top_k=6):
        context = await self.news_context(task_id)
        vector = validate_vectors(await self.embedding.embed([query]), 1)[0]
        store = NewsStore(self.store)
        rows = await self.db(store.search, context.corp_code, context.company_name,
            context.created_at, self.settings.news_retention_days, vector, top_k)
        collection = await self.db(store.status)
        if "details" in collection:
            collection["details"] = {k: v for k, v in collection["details"].items() if k != "queries"}
        return {"articles": rows, "as_of": context.created_at.isoformat(),
                "collection": collection,
                "limitations": ["기업 태그와 공통 시황 여부는 제목에 대한 모델 판단입니다. 본문은 아직 확인하지 않았습니다."]
                + ([] if rows else ["기준 시각 이전에 저장된 관련 시황 뉴스가 없습니다."])}

    async def read_market_news(self, task_id, article_ids):
        context = await self.news_context(task_id)
        store = NewsStore(self.store)
        rows = await self.db(store.articles, article_ids, context.corp_code, context.company_name,
            context.created_at, self.settings.news_retention_days)
        documents, sources, limitations = [], [], []
        if len(rows) != len(set(article_ids)):
            limitations.append("조회 범위 또는 기준 시각에 맞지 않는 기사 식별자를 제외했습니다.")
        import asyncio
        async def fetch(row):
            try:
                article = await self.sources.news_article(row["url"])
                published = datetime.fromisoformat(article["published_at"])
                modified = datetime.fromisoformat(article["modified_at"]) if article.get("modified_at") else published
                if (published.tzinfo is None or modified.tzinfo is None
                        or published > context.created_at or modified > context.created_at
                        or article["url"] != row["url"] or not article.get("text", "").strip()):
                    raise ValueError("NEWS_OUTSIDE_CUTOFF")
                doc_id = "news:" + row["id"] + ":" + hashlib.sha256(article["text"].encode()).hexdigest()[:16]
                document = {"document_id": doc_id, "text": article["text"], "url": row["url"],
                            "published_at": article["published_at"], "evidence_scope": "news_article"}
                return document, {"document_id": doc_id, "location": "article:body", "quote": article["text"],
                                  "url": row["url"], "published_at": article["published_at"]}
            except Exception as error:
                limitations.append("기사 본문 미확인: " + row["id"] + " " + type(error).__name__)
                return None
        for found in await asyncio.gather(*(fetch(row) for row in rows)):
            if found:
                documents.append(found[0])
                sources.append(found[1])
        return {"documents": documents, "sources": sources, "limitations": limitations,
                "as_of": context.created_at.isoformat()}
