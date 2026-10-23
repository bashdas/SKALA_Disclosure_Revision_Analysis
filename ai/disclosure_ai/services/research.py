"""분석 대상 기업의 증권사 리포트를 AI 저장소에서 임베딩하고 검색합니다."""

import hashlib
import json
import math
import os
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from openai import AsyncOpenAI
from pydantic import Field, TypeAdapter, field_validator

from disclosure_ai.schemas import Model
from disclosure_ai.services.documents import validated_sources


class ResearchReport(Model):
    report_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    title: str = Field(min_length=1, max_length=255)
    company_name: str = Field(min_length=1, max_length=255)
    corp_code: str = Field(pattern=r"^[0-9]{8}$")
    published_at: date
    url: str | None = None
    source_file: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1, max_length=100000)

    @field_validator("url")
    @classmethod
    def public_url(cls, value):
        if value is not None:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"https", "http"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise ValueError("INVALID_RESEARCH_URL")
        return value


def chunks(report):
    """쪽 번호와 줄 범위를 유지하며 표의 한 줄을 함께 검색합니다."""
    page, start, lines = None, 1, []
    result = []

    def append():
        if lines:
            result.append(
                {
                    "document_id": "research:" + report.report_id,
                    "location": f"page:{page or 'unknown'}:lines:{start}-{start + len(lines) - 1}",
                    "quote": "\n".join(lines),
                    "url": report.url,
                    "published_at": report.published_at.isoformat(),
                }
            )

    for number, line in enumerate(report.text.splitlines(), 1):
        marker = re.fullmatch(r"\[(\d+)쪽\]", line.strip())
        # 쪽 경계를 넘기면 수정할 원문 위치가 모호해지므로 경계에서 조각을 닫습니다.
        if marker or sum(len(value) + 1 for value in lines) + len(line) > 1200:
            append()
            lines, start = [], number
        if marker:
            page = marker[1]
        if len(line) > 6000:
            raise ValueError("RESEARCH_LINE_TOO_LARGE")
        lines.append(line)
    append()
    # 쪽 표기가 있는 전사에서는 원문 앞에 붙인 파일 설명을 검색 근거에서 제외합니다.
    paged = any(not item["location"].startswith("page:unknown:") for item in result)
    return [
        item
        for item in result
        if item["quote"].strip() and (not paged or not item["location"].startswith("page:unknown:"))
    ]


class ResearchIndex:
    def __init__(self, ledger, embed=None):
        self.ledger, self.embed = ledger, embed
        self.path = Path(
            os.environ.get(
                "AI_RESEARCH_REPORTS_PATH",
                str(Path(__file__).parents[1] / "data" / "research_reports.json"),
            )
        )
        self.catalog = None

    def eligible(self, request, filing):
        if self.catalog is None:
            if self.path.stat().st_size > 5 * 1024 * 1024:
                raise ValueError("RESEARCH_CATALOG_TOO_LARGE")
            catalog = TypeAdapter(list[ResearchReport]).validate_json(self.path.read_bytes())
            ids = [item.report_id for item in catalog]
            if len(ids) != len(set(ids)) or len(ids) > 100:
                raise ValueError("INVALID_RESEARCH_CATALOG")
            self.catalog = catalog
        # SEC 접수번호에도 같은 기준을 적용하려면 공식 filed_at 날짜가 필요합니다.
        receipt = request["disclosure_receipt_no"]
        published = filing.get("filed_at") or (
            receipt[:8] if not receipt.startswith("SEC:") else None
        )
        if not published:
            return []
        cutoff = date.fromisoformat(str(published)[:10])
        return [
            report
            for report in self.catalog
            if report.published_at <= cutoff
            and report.corp_code == request.get("corp_code")
        ]

    async def vectors(self, texts):
        if self.embed:
            values = await self.embed(texts)
        else:
            async with AsyncOpenAI(max_retries=0, timeout=8) as client:
                response = await client.embeddings.create(
                    model="text-embedding-3-small",
                    input=texts,
                    dimensions=1536,
                )
            rows = sorted(response.data, key=lambda row: row.index)
            if [row.index for row in rows] != list(range(len(texts))):
                raise ValueError("INVALID_EMBEDDING_ORDER")
            values = [row.embedding for row in rows]
        if len(values) != len(texts) or any(
            len(vector) != 1536 or not all(math.isfinite(x) for x in vector) or not any(vector)
            for vector in values
        ):
            raise ValueError("INVALID_RESEARCH_EMBEDDING")
        return [[x / math.hypot(*vector) for x in vector] for vector in values]

    async def search(self, request, filing, scope, query):
        reports = self.eligible(request, filing)
        if not reports:
            return {"documents": [], "sources": [], "research_reports": []}
        if not query.strip() or len(query) > 2000:
            raise ValueError("INVALID_RESEARCH_QUERY")
        fragments = [source for report in reports for source in chunks(report)]
        if not fragments:
            raise ValueError("EMPTY_RESEARCH_REPORT")
        db = self.ledger.db
        db.execute(
            "CREATE TABLE IF NOT EXISTS research_embeddings "
            "(cache_key TEXT PRIMARY KEY, vector TEXT NOT NULL)"
        )
        vectors, missing = {}, {}
        for source in fragments:
            key = hashlib.sha256(
                json.dumps(
                    [scope, "text-embedding-3-small:1536:lines-v1", source["quote"]],
                    ensure_ascii=False,
                ).encode()
            ).hexdigest()
            source["cache_key"] = key
            cached = db.execute(
                "SELECT vector FROM research_embeddings WHERE cache_key=?", (key,)
            ).fetchone()
            if cached:
                vectors[key] = json.loads(cached[0])
            else:
                missing[key] = source["quote"]
        # 테스트용 소수 리포트의 범위만 전수 비교하므로 별도 벡터 서버를 두지 않습니다.
        values = await self.vectors([*missing.values(), query])
        for key, vector in zip(missing, values[:-1], strict=True):
            vectors[key] = vector
        with db:
            db.executemany(
                "INSERT OR IGNORE INTO research_embeddings VALUES (?,?)",
                [(key, json.dumps(vectors[key])) for key in missing],
            )
        ranked = sorted(
            fragments,
            key=lambda source: (
                -sum(a * b for a, b in zip(vectors[source["cache_key"]], values[-1], strict=True))
            ),
        )[:3]
        return {
            "documents": [
                {
                    "document_id": "research:" + report.report_id,
                    "text": report.text,
                    "url": report.url,
                    "published_at": report.published_at.isoformat(),
                }
                for report in reports
            ],
            "sources": [{k: v for k, v in source.items() if k != "cache_key"} for source in ranked],
            "research_reports": [
                {
                    "document_id": "research:" + report.report_id,
                    "title": report.title,
                    "source_file": report.source_file,
                    "published_at": report.published_at.isoformat(),
                    "corp_code": report.corp_code,
                }
                for report in reports
            ],
        }


async def search_reports(run, state, query):
    if not {"corp_code", "disclosure_receipt_no"} <= state["request"].keys():
        return {"error": "INVALID_RESEARCH_INPUT"}

    async def invoke(_name, _args):
        if hasattr(run.tools, "search_research_reports"):
            # Production never falls back to the shared local fixture catalog.
            return await run.tools.search_research_reports(run.h.task_id, query)
        try:
            return await run.research.search(
                state["request"], state["filing"], state["scope"], query
            )
        except (ValueError, TypeError, KeyError, OSError):
            return {"error": "INVALID_RESEARCH_INPUT"}

    return await run.h.tool(
        "search_research_reports",
        {
            "query": query,
            "corp_code": state["request"]["corp_code"],
            "receipt_no": state["request"]["disclosure_receipt_no"],
        },
        invoke,
        scope=state["scope"],
    )


def verified_research(data, state):
    """원문 위치와 공시 근거가 연결된 제안만 보고서에 전달합니다."""
    documents, fragments = state.get("documents", []), state.get("context", [])
    linked = {item["document_id"] for item in state.get("research_reports", [])}
    filing_ids = {doc["document_id"] for doc in state.get("filing", {}).get("documents", [])}
    supplements, revisions = [], []
    for key, target in (("memo_supplements", supplements), ("report_revisions", revisions)):
        for item in data.get(key, []):
            document_id = item.get(
                "report_document_id" if key == "memo_supplements" else "document_id"
            )
            location = item.get("report_location" if key == "memo_supplements" else "location")
            matched = next(
                (
                    source
                    for source in fragments
                    if source["document_id"] == document_id
                    and source["document_id"] in linked
                    and source["location"] == location
                ),
                None,
            )
            if not matched:
                continue
            evidence = validated_sources([*item.get("evidence", []), matched], documents, fragments)
            ids = {source["document_id"] for source in evidence}
            if not (ids & linked and ids & filing_ids and item.get("reason", "").strip()):
                continue
            if key == "report_revisions":
                # 모델이 표의 열을 이어 붙이지 않도록 선택한 위치의 원문을 직접 복원합니다.
                item = {**item, "before_text": matched["quote"]}
            elif not item.get("text", "").strip() or item["text"] in state.get("memo", {}).get(
                "text", ""
            ):
                continue
            target.append(
                {
                    **item,
                    "evidence": evidence,
                    "memo_id": state["request"]["memo_id"],
                    "base_memo_version": state["request"]["base_memo_version"],
                }
            )
    return {"memo_supplements": supplements, "report_revisions": revisions}
