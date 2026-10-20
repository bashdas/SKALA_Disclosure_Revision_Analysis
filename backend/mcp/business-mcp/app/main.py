from contextlib import asynccontextmanager

from fastapi import FastAPI
import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from disclosure_shared.health import HealthResponse

from app.client import BusinessAPIClient
from app.config import Settings
from app.tools import register_tools


def create_app(settings: Settings | None = None, *, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings or Settings()
    client = BusinessAPIClient(settings, transport=transport)
    mcp = FastMCP("business-mcp", stateless_http=True, json_response=True,
        host=settings.business_mcp_host, port=settings.business_mcp_port, streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
            allowed_hosts=settings.mcp_allowed_hosts))
    register_tools(mcp, client)
    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with client:
            async with mcp.session_manager.run():
                yield

    app = FastAPI(title="business-mcp", version="0.1.0", lifespan=lifespan)
    app.state.mcp = mcp

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(service="business-mcp")

    app.mount("/", mcp_app)
    return app


app = create_app()
