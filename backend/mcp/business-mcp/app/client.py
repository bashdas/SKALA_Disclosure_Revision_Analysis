"""HTTP-only adapter; business rules and persistence belong to Business API."""
import json
import re
from typing import Any

import httpx
from mcp.server.fastmcp.exceptions import ToolError

from app.config import Settings


class BusinessAPIClient:
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        self.settings, self.transport = settings, transport
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._http = httpx.AsyncClient(base_url=self.settings.business_api_base_url,
            timeout=self.settings.business_mcp_request_timeout_seconds,
            follow_redirects=False, trust_env=False, transport=self.transport)
        return self

    async def __aexit__(self, *args):
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def _safe(self, value):
        key = self.settings.internal_api_key.get_secret_value()
        if isinstance(value, str):
            return value.replace(key, "[REDACTED]") if key else value
        if isinstance(value, list):
            return [self._safe(item) for item in value]
        if isinstance(value, dict):
            sensitive = {"internalapikey", "xinternalapikey", "authorization", "password", "passwordhash",
                         "jwtsecretkey", "databaseurl", "rabbitmqurl"}
            return {self._safe(name): self._safe(item) for name, item in value.items()
                    if name.lower().replace("-", "").replace("_", "") not in sensitive}
        return value

    def _error(self, kind: str, code: str, message: str, status_code: int | None = None):
        # SDK exposes ToolError as an MCP error result; never propagate raw HTTP exceptions.
        data = {"kind": kind, "status_code": status_code, "code": code, "message": message}
        raise ToolError(json.dumps(self._safe(data), ensure_ascii=False)) from None

    async def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        key = self.settings.internal_api_key.get_secret_value()
        if len(key.encode("utf-8")) < 32 or key.lower().startswith("change-me") or self._http is None:
            self._error("configuration", "BUSINESS_API_CONFIGURATION_ERROR", "Business API client unavailable")
        try:
            response = await self._http.request(method, path, json=body, headers={"X-Internal-API-Key": key})
        except httpx.TimeoutException:
            self._error("timeout", "BUSINESS_API_TIMEOUT", "Business API request timed out")
        except httpx.RequestError:
            self._error("connection_failure", "BUSINESS_API_CONNECTION_FAILED", "Business API connection failed")
        if response.is_client_error or response.is_server_error:
            kind = "business_api_4xx" if response.is_client_error else "business_api_5xx"
            code, message = "BUSINESS_API_ERROR", "Business API request failed"
            try:
                error = response.json().get("error", {})
                if isinstance(error, dict):
                    candidate, text = error.get("code"), error.get("message")
                    if isinstance(candidate, str) and re.fullmatch(r"[A-Z0-9_]{1,100}", candidate):
                        code = candidate
                    if isinstance(text, str) and len(text) <= 500 and not any(word in text.lower() for word in ("traceback", "://", "stack trace")):
                        message = text.replace("\n", " ").replace("\r", " ")
            except (ValueError, AttributeError):
                pass
            self._error(kind, code, message, response.status_code)
        if not response.is_success:
            self._error("malformed_response", "BUSINESS_API_INVALID_RESPONSE", "Unexpected Business API response", response.status_code)
        try:
            result = response.json()
        except ValueError:
            self._error("malformed_response", "BUSINESS_API_INVALID_RESPONSE", "Business API returned invalid JSON", response.status_code)
        if not isinstance(result, dict):
            self._error("malformed_response", "BUSINESS_API_INVALID_RESPONSE", "Business API response must be an object", response.status_code)
        return self._safe(result)
