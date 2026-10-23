"""Task-authorized internal report retrieval with immutable page positions."""
from uuid import UUID
from datetime import date
from pydantic import BaseModel, Field

from app.chunking import Chunk
from app.embedding import validate_vectors
from app.errors import RagError


class Page(BaseModel):
    page: int = Field(ge=1)
    text: str = Field(max_length=1_000_000)


class Report(BaseModel):
    report_id: UUID
    version: int = Field(ge=1)
    title: str
    corp_code: str
    company_name: str
    published_at: date
    source_file: str
    text: str = Field(min_length=1, max_length=1_010_000)
    pages: list[Page] = Field(max_length=300)
    content_hash: str


def report_chunks(report, size=1000):
    chunks = []
    for page in report.pages:
        # Character offsets preserve exact quotes, including extracted table rows.
        lines = page.text.splitlines(keepends=True)
        start, buffer = 0, ""
        for line in lines:
            if len(line) > 6000:
                raise RagError("REPORT_LINE_TOO_LARGE", "내부 리포트의 표 또는 문장이 너무 깁니다.")
            if buffer and len(buffer) + len(line) > size:
                chunks.append(Chunk(buffer, {"page": page.page, "location": f"page:{page.page}:chars:{start}-{start + len(buffer)}"}))
                start += len(buffer)
                buffer = ""
            buffer += line
        if buffer.strip():
            chunks.append(Chunk(buffer, {"page": page.page, "location": f"page:{page.page}:chars:{start}-{start + len(buffer)}"}))
    if not chunks:
        raise RagError("EMPTY_REPORT", "검색 가능한 내부 리포트 본문이 없습니다.")
    return chunks


async def search_reports(service, task_id, query, top_k):
    context = await service.context(task_id)
    payload = await service.sources.get_research_reports(task_id)
    try:
        if UUID(payload["task_id"]) != task_id or UUID(payload["organization_id"]) != context.organization_id:
            raise ValueError()
        if len(payload["reports"]) > 100:
            raise ValueError()
        reports = [Report.model_validate(row) for row in payload["reports"]]
        if any(r.corp_code != context.corp_code for r in reports):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise RagError("INVALID_REPORT_CONTEXT", "내부 리포트 조회 범위를 확인하지 못했습니다.") from None
    if not reports:
        return {"documents": [], "sources": [], "research_reports": []}
    fingerprint = service.settings.rag_embedding_model + ":1536:report-page-lines-v1"
    indexed = []
    for report in reports:
        identity = dict(organization_id=context.organization_id, document_type="INTERNAL_REPORT",
            identifier=str(report.report_id), version=str(report.version), content_hash=report.content_hash,
            fingerprint=fingerprint)
        document_id = f"research:{report.report_id}:v{report.version}"
        source = {"document_id": document_id, "report_id": str(report.report_id), "version": report.version,
            "title": report.title, "corp_code": report.corp_code, "source_file": report.source_file,
            "published_at": report.published_at.isoformat(), "url": None}
        cached = await service.db(service.store.find_document, identity)
        if cached is None:
            chunks = report_chunks(report)
            vectors = validate_vectors(await service.embedding.embed([c.text for c in chunks]), len(chunks))
            cached = await service.db(service.store.save_document, identity, source, chunks, vectors)
        indexed.append(cached["id"])
    vector = validate_vectors(await service.embedding.embed([query]), 1)[0]
    rows = await service.db(service.store.search_reports, context.organization_id, indexed, fingerprint,
        vector, top_k, service.settings.rag_min_similarity)
    selected = {row["document_id"] for row in rows}
    return {"documents": [{"document_id": f"research:{r.report_id}:v{r.version}", "text": r.text,
                "url": None, "published_at": r.published_at.isoformat()} for r in reports
                if f"research:{r.report_id}:v{r.version}" in selected],
        "sources": rows,
        "research_reports": [{"document_id": f"research:{r.report_id}:v{r.version}",
            "report_id": str(r.report_id), "version": r.version, "title": r.title,
            "corp_code": r.corp_code, "source_file": r.source_file,
            "published_at": r.published_at.isoformat()} for r in reports
            if f"research:{r.report_id}:v{r.version}" in selected]}
