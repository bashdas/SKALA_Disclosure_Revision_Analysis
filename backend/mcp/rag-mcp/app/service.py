import hashlib
import json
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from app.chunking import Chunker
from app.embedding import validate_vectors
from app.errors import RagError


class MemoContext(BaseModel):
    id: UUID
    version: int = Field(ge=1)
    content: str = Field(min_length=1)
    content_hash: str | None = None


class AnalysisContext(BaseModel):
    task_id: UUID
    organization_id: UUID
    memo: MemoContext
    disclosure_receipt_no: str = Field(pattern=r"^\d{14}$")


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
