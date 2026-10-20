from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import re
from typing import Any

from fastapi import FastAPI
import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.concurrency import run_in_threadpool
from disclosure_shared.health import HealthResponse

from app.client import OpenDartClient
from app.config import Settings
from app.errors import OpenDartError
from app.parser import OpenDartDocumentParser


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
    parser = OpenDartDocumentParser()
    mcp = FastMCP("external-mcp", stateless_http=True, json_response=True,
        host=settings.external_mcp_host, port=settings.external_mcp_port, streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
            allowed_hosts=settings.mcp_allowed_hosts))

    @mcp.tool()
    async def get_disclosure(receipt_no: str) -> dict[str, Any]:
        """Retrieve OpenDART original text/tables and exact receipt metadata. No impact analysis."""
        try:
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
        except OpenDartError as error:
            raise ToolError(json.dumps(error.as_dict(), ensure_ascii=False)) from None

    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with client:
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
