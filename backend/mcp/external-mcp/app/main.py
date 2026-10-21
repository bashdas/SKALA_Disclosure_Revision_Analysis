from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
import json
import re
from typing import Annotated, Any, Literal
from pydantic import Field

from fastapi import FastAPI
import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.concurrency import run_in_threadpool
from disclosure_shared.health import HealthResponse

from app import sec
from app.client import OpenDartClient
from app.catalog import DisclosureCatalog
from app.config import Settings
from app.errors import OpenDartError
from app.parser import OpenDartDocumentParser
from app.scholar import GoogleScholarClient, ScholarError


def _value(row, name):
    value = row.get(name) if row else None
    return value if isinstance(value, str) and value.strip() else None


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[REDACTED]") if key else value
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {_redact(name, key): _redact(item, key) for name, item in value.items()}
    return value


def create_app(settings: Settings | None = None, *, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings or Settings()
    client = OpenDartClient(settings, transport=transport)
    scholar = GoogleScholarClient(settings, transport=transport)
    parser = OpenDartDocumentParser()
    catalog = DisclosureCatalog(client)
    mcp = FastMCP("external-mcp", stateless_http=True, json_response=True,
        host=settings.external_mcp_host, port=settings.external_mcp_port, streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
            allowed_hosts=settings.mcp_allowed_hosts))

    @mcp.tool()
    async def get_disclosure(receipt_no: str) -> dict[str, Any]:
        """Retrieve OpenDART original text/tables and exact receipt metadata. No impact analysis."""
        try:
            if receipt_no.startswith("SEC:"):
                return await sec.disclosure(receipt_no, parser, settings, transport)
            if not re.fullmatch(r"[0-9]{14}", receipt_no):
                raise OpenDartError("INVALID_RECEIPT_NO")
            raw = await client.get_document(receipt_no)
            document = await run_in_threadpool(parser.parse, raw)
            row, metadata_status = await client.find_metadata(receipt_no)
            filed_at = None
            date = _value(row, "rcept_dt")
            if date and re.fullmatch(r"[0-9]{8}", date):
                try:
                    filed_at = datetime.strptime(date, "%Y%m%d").date().isoformat()
                except ValueError:
                    pass
            corp_code = _value(row, "corp_code")
            if corp_code and not re.fullmatch(r"[0-9]{8}", corp_code):
                corp_code = None
            result = {"receipt_no": receipt_no, "corp_code": corp_code,
                "company_name": _value(row, "corp_name"), "report_name": _value(row, "report_nm"),
                "filed_at": filed_at, "document": document, "metadata_status": metadata_status,
                "source": {"provider": "OPENDART", "source_type": "REGULATORY_FILING",
                    "identifier": receipt_no, "published_at": filed_at,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "original_location": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt_no}"}}
            return _redact(result, settings.opendart_api_key.get_secret_value())
        except (httpx.HTTPError, ValueError, KeyError, IndexError):
            raise ToolError('{"code":"SEC_SOURCE_FAILED","message":"SEC 원문과 메타데이터를 확인하지 못했습니다."}') from None
        except OpenDartError as error:
            raise ToolError(json.dumps(error.as_dict(), ensure_ascii=False)) from None

    @mcp.tool()
    async def get_financial_statements(
        corp_code: Annotated[str, Field(pattern=r"^[0-9]{8}$")],
        bsns_year: Annotated[int, Field(ge=2015, le=2100)],
        reprt_code: Literal["11011", "11012", "11013", "11014"],
        fs_div: Literal["CFS", "OFS"],
    ) -> dict[str, Any]:
        """기업, 사업연도와 연결 또는 별도 구분으로 OpenDART 재무제표를 조회합니다."""
        try:
            accounts = await client.get_financial_statements(corp_code, bsns_year, reprt_code, fs_div)
            sources = []
            for receipt in dict.fromkeys(row["rcept_no"] for row in accounts):
                metadata, status = await client.find_metadata(receipt)
                published_at = None
                if metadata and isinstance(metadata.get("rcept_dt"), str):
                    try:
                        published_at = datetime.strptime(metadata["rcept_dt"], "%Y%m%d").date().isoformat()
                    except ValueError:
                        pass
                sources.append({"provider": "OPENDART", "identifier": receipt,
                    "published_at": published_at, "metadata_status": status,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "original_location": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}"})
            return _redact({"corp_code": corp_code, "bsns_year": bsns_year,
                "reprt_code": reprt_code, "fs_div": fs_div,
                "accounts": accounts, "sources": sources}, settings.opendart_api_key.get_secret_value())
        except OpenDartError as error:
            raise ToolError(json.dumps(error.as_dict(), ensure_ascii=False)) from None

    @mcp.tool()
    async def search_academic_papers(
        query: Annotated[str, Field(min_length=1, max_length=500, pattern=r"\S")],
        limit: Annotated[int, Field(ge=1, le=20)] = 5,
        year_from: Annotated[int, Field(ge=1800, le=2100)] | None = None,
        year_to: Annotated[int, Field(ge=1800, le=2100)] | None = None,
    ) -> dict[str, Any]:
        """Search Google Scholar via SerpApi. Returns bibliographic search snippets, not full papers."""
        if year_from is not None and year_to is not None and year_from > year_to:
            raise ToolError('{"code":"INVALID_SCHOLAR_QUERY","message":"Invalid year range"}')
        try:
            result = await scholar.search(query, limit, year_from, year_to)
            return _redact(_redact(result, settings.serpapi_api_key.get_secret_value()),
                settings.opendart_api_key.get_secret_value())
        except ScholarError as error:
            raise ToolError(json.dumps({"code": error.code, "message": str(error)})) from None

    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
    async def opendart_search_companies(query: Annotated[str, Field(max_length=100)],
        limit: Annotated[int, Field(ge=1, le=100)] = 20, offset: Annotated[int, Field(ge=0)] = 0) -> dict[str, Any]:
        """회사명 또는 종목코드로 회사를 검색해 items, total_count와 has_more를 반환합니다."""
        try:
            if query.startswith("SEC:"):
                return await sec.search_company(query, settings, transport)
            return await catalog.search_companies(query, limit, offset)
        except OpenDartError as error:
            raise ToolError(json.dumps(error.as_dict(), ensure_ascii=False)) from None

    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
    async def opendart_search_disclosures(start_date: date, end_date: date,
        corp_code: Annotated[str | None, Field(pattern=r"^(?:[0-9]{8}|SEC:[0-9]{1,10})$")] = None,
        page: Annotated[int, Field(ge=1, le=10000)] = 1, query: Annotated[str, Field(max_length=100)] = "") -> dict[str, Any]:
        """선택한 회사와 기간의 공시를 조회해 items, total_count와 has_more를 반환합니다."""
        try:
            if corp_code and corp_code.startswith("SEC:"):
                return await sec.search_filings(corp_code, start_date, end_date, page, query, settings, transport)
            return await catalog.search_disclosures(corp_code, start_date, end_date, page, query)
        except OpenDartError as error:
            raise ToolError(json.dumps(error.as_dict(), ensure_ascii=False)) from None

    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
    async def opendart_get_disclosure_family(receipt_no: Annotated[str, Field(pattern=r"^[0-9]{14}$")]) -> dict[str, Any]:
        """공시 접수번호에 대해 DART가 연결한 본문 목록과 source_url을 반환합니다."""
        try:
            return await catalog.family(receipt_no)
        except OpenDartError as error:
            raise ToolError(json.dumps(error.as_dict(), ensure_ascii=False)) from None

    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with client, scholar:
            async with mcp.session_manager.run():
                yield

    app = FastAPI(title="external-mcp", version="0.1.0", lifespan=lifespan)
    app.state.mcp = mcp

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(service="external-mcp")

    app.mount("/", mcp_app)
    return app


app = create_app()
