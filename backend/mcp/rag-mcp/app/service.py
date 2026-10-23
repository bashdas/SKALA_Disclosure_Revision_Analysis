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
    memo: MemoContext
    corp_code: str | None = None
    company_name: str | None = None
    created_at: datetime | None = None
    disclosure_receipt_no: str = Field(
        pattern=r"^(?:[0-9]{14}|SEC:[0-9]{1,10}:[0-9]{10}-[0-9]{2}-[0-9]{6})$"
    )


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


class RagService:
    def __init__(self, sources, embedding, store, settings):
        self.sources, self.embedding, self.store, self.settings = (
            sources,
            embedding,
            store,
            settings,
        )
        self.chunker = Chunker(settings.rag_chunk_size, settings.rag_chunk_overlap)
        self.fingerprint = (
            f"{settings.rag_embedding_model}:1536:{self.chunker.fingerprint}"
        )

    async def context(self, task_id):
        try:
            context = AnalysisContext.model_validate(
                await self.sources.get_context(task_id)
            )
            if context.task_id != task_id:
                raise ValueError("Task mismatch")
            return context
        except (ValidationError, ValueError, TypeError):
            raise RagError(
                "INVALID_ANALYSIS_CONTEXT", "Business MCP returned an invalid context"
            ) from None

    async def db(self, method, *args):
        try:
            return await run_in_threadpool(method, *args)
        except Exception:
            raise RagError(
                "RAG_DATABASE_FAILED", "RAG database operation failed"
            ) from None

    async def index_document(
        self, context, kind, identifier, version, text, source, document=None
    ):
        identity = dict(
            document_type=kind,
            identifier=identifier,
            version=str(version),
            content_hash=digest([text, document, source.get("upstream_content_hash")]),
            fingerprint=self.fingerprint,
        )
        cached = await self.db(self.store.find_document, identity)
        if cached:
            return cached
        chunks = self.chunker.split(text, document)
        vectors = validate_vectors(
            await self.embedding.embed([c.text for c in chunks]), len(chunks)
        )
        return await self.db(
            self.store.save_document, identity, source, chunks, vectors
        )

    async def ensure_analysis_index(self, task_id):
        context = await self.context(task_id)
        disclosure = await self.sources.get_disclosure(context.disclosure_receipt_no)
        try:
            if disclosure["receipt_no"] != context.disclosure_receipt_no:
                raise ValueError("Receipt mismatch")
            document = disclosure["document"]
            if not isinstance(document["text"], str) or not document["text"].strip():
                raise ValueError("Missing text")
            source = {
                **disclosure["source"],
                "receipt_no": disclosure["receipt_no"],
                "corp_code": disclosure.get("corp_code"),
                "company_name": disclosure.get("company_name"),
            }
            # Retrieval timestamps/ZIP packaging do not change the parsed document identity.
            document = {
                k: document[k] for k in ("text", "blocks", "tables") if k in document
            }
        except (KeyError, TypeError, ValueError):
            raise RagError(
                "INVALID_DISCLOSURE", "External MCP returned an invalid disclosure"
            ) from None
        memo_source = {
            "provider": "BUSINESS_MCP",
            "identifier": str(context.memo.id),
            "memo_id": str(context.memo.id),
            "version": context.memo.version,
            "upstream_content_hash": context.memo.content_hash,
        }
        memo = await self.index_document(
            context,
            "MEMO",
            str(context.memo.id),
            context.memo.version,
            context.memo.content,
            memo_source,
        )
        filing = await self.index_document(
            context,
            "DISCLOSURE",
            disclosure["receipt_no"],
            "snapshot",
            document["text"],
            source,
            document,
        )
        await self.db(
            self.store.link, task_id, memo["id"], filing["id"]
        )
        return {
            "task_id": str(task_id),
            "indexed": True,
            "memo_chunks": memo["chunks"],
            "disclosure_chunks": filing["chunks"],
            "sources": [memo["source"], filing["source"]],
        }

    async def search_evidence(self, task_id, query, top_k=5, document_types=None):
        context = await self.context(task_id)
        vector = validate_vectors(await self.embedding.embed([query]), 1)[0]
        results = await self.db(
            self.store.search,
            task_id,
            context.memo.id,
            context.memo.version,
            context.disclosure_receipt_no,
            self.fingerprint,
            vector,
            ["MEMO", "DISCLOSURE"] if document_types is None else document_types,
            top_k,
            self.settings.rag_min_similarity,
        )
        if results is None:
            raise RagError(
                "INDEX_NOT_READY", "Run ensure_analysis_index for this task first"
            )
        return {
            "query": query,
            "score_kind": "normalized_cosine_similarity_higher_is_better",
            "results": results,
        }

    async def search_research_reports(self, task_id, query, top_k=5):
        from app.research import search_reports
        return await search_reports(self, task_id, query, top_k)

    async def news_context(self, task_id):
        context = await self.context(task_id)
        if not context.created_at or context.created_at.tzinfo is None:
            raise RagError(
                "NEWS_CUTOFF_UNAVAILABLE", "분석 요청 시각을 확인하지 못했습니다."
            )
        return context

    @staticmethod
    def headline_evidence(rows):
        documents, sources = [], []
        for row in rows:
            doc_id = (
                "news:"
                + row["id"]
                + ":"
                + digest([row["title"], row["published_at"]])[:16]
            )
            documents.append(
                {
                    "document_id": doc_id,
                    "text": row["title"],
                    "url": row["url"],
                    "published_at": row["published_at"],
                    "evidence_scope": "news_title",
                    "title_only": True,
                    "article_snapshot": row,
                }
            )
            sources.append(
                {
                    "document_id": doc_id,
                    "location": "news:title",
                    "quote": row["title"],
                    "url": row["url"],
                    "published_at": row["published_at"],
                }
            )
        return {"documents": documents, "sources": sources}

    async def search_market_news(
        self, task_id, query, top_k=6, as_of=None, days=7, scopes=None, topics=None
    ):
        from datetime import time, timedelta, timezone
        from zoneinfo import ZoneInfo

        context = await self.news_context(task_id)
        cutoff = context.created_at
        if as_of:
            try:
                if len(as_of) == 10:
                    selected = datetime.combine(
                        datetime.fromisoformat(as_of).date(),
                        time.max,
                        ZoneInfo("Asia/Seoul"),
                    )
                else:
                    selected = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
                if selected.tzinfo is None:
                    raise ValueError()
                cutoff = min(selected, context.created_at)
            except (ValueError, TypeError):
                raise RagError(
                    "NEWS_CUTOFF_INVALID",
                    "시황 기준 시각은 시간대가 있는 ISO 시각 또는 한국 날짜입니다.",
                ) from None
        historical = cutoff < context.created_at
        metadata = {
            "as_of": cutoff.isoformat(),
            "days": days,
            "mode": "HISTORICAL" if historical else "CURRENT",
            "range_start": (cutoff - timedelta(days=days)).isoformat(),
            "title_only": True,
            "scopes": scopes or ["COMPANY", "INDUSTRY", "MACRO"],
            "topic_tags": topics or [],
            "provider": "네이버 검색결과",
        }
        if not self.settings.news_usage_authorization.strip():
            return {
                **metadata,
                "articles": [],
                "documents": [],
                "sources": [],
                "error": "NEWS_USAGE_NOT_AUTHORIZED",
                "reason_codes": ["NEWS_USAGE_NOT_AUTHORIZED"],
                "limitations": [
                    "네이버 검색 데이터의 저장 및 AI 이용에 관한 별도 허용 조건이 없어 뉴스 분석을 비활성화했습니다."
                ],
            }
        store = NewsStore(self.store)
        vector = None
        warnings, codes = [], []
        if self.settings.news_embedding_enabled:
            try:
                vector = validate_vectors(await self.embedding.embed([query]), 1)[0]
            except Exception:
                warnings.append(
                    "제목 임베딩 검색이 실패해 메타데이터와 제목 단어 검색을 사용했습니다."
                )
                codes.append("NEWS_EMBEDDING_FAILED")
        rows = await self.db(
            store.search,
            context.corp_code,
            context.company_name,
            cutoff,
            days,
            vector,
            top_k,
            query,
            scopes,
            topics,
            self.settings.news_company_industries.get(context.corp_code or "", []),
        )
        collection = await self.db(store.status)
        # 전체 즐겨찾기 목록과 검색어는 분석 모델 및 사용자에게 전달하지 않습니다.
        collection = {
            k: v
            for k, v in collection.items()
            if k in {"status", "started_at", "finished_at"}
        }
        finished = collection.get("finished_at")
        if not finished:
            codes.append("NEWS_NOT_COLLECTED")
            warnings.append(
                "수집을 완료한 기록이 없습니다. 관련 뉴스의 존재 여부를 판단할 수 없습니다."
            )
        elif datetime.now(timezone.utc) - datetime.fromisoformat(finished) > timedelta(
            hours=self.settings.news_stale_hours
        ):
            codes.append("NEWS_STALE")
            warnings.append("수집 자료가 최신성 기준을 넘었습니다.")
        if collection.get("status") == "FAILED":
            codes.append("NEWS_COLLECTION_FAILED")
        if not rows:
            codes.append("NEWS_NO_MATCH_IN_STORE")
            warnings.append(
                "지정한 기준 시각과 조회 기간에 시스템이 확보한 관련 제목이 없습니다. 관련 뉴스가 실제로 없다는 뜻은 아닙니다."
            )
        if historical:
            warnings.append(
                "과거 기준 시각까지 수집과 분류를 완료한 활성 자료만 검색했습니다. 당시 전체 뉴스의 복원은 보장하지 않습니다."
            )
        evidence = self.headline_evidence(rows)
        for document in evidence["documents"]:
            document["news_retrieval"] = metadata
        return {
            **metadata,
            "articles": rows,
            **evidence,
            "collection": collection,
            "reason_codes": codes,
            "limitations": [
                *warnings,
                "뉴스 제목만 수집했습니다. 태그와 주관적 신뢰도는 분류 결과이며 본문 사실의 검증이나 확률이 아닙니다.",
            ],
        }

    async def read_market_news(self, task_id, article_ids):
        # 기존 도구 호출과의 호환성을 유지하며 외부 기사 본문에 접속하지 않습니다.
        context = await self.news_context(task_id)
        if not self.settings.news_usage_authorization.strip():
            return {
                "error": "NEWS_USAGE_NOT_AUTHORIZED",
                "documents": [],
                "sources": [],
            }
        rows = await self.db(
            NewsStore(self.store).articles,
            article_ids,
            context.corp_code,
            context.company_name,
            context.created_at,
            30,
            self.settings.news_company_industries.get(context.corp_code or "", []),
        )
        return {
            "articles": rows,
            **self.headline_evidence(rows),
            "title_only": True,
            "as_of": context.created_at.isoformat(),
            "limitations": [
                "저장된 뉴스 제목만 반환했습니다. 본문은 조회하지 않았습니다."
            ],
        }
