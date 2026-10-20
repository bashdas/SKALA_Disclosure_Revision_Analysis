from datetime import datetime
import json
import logging
import re
from typing import Any

import httpx
from lxml import etree

from app.config import Settings
from app.errors import OpenDartError, check_status


class _KeyQueryFilter(logging.Filter):
    def filter(self, record):
        # httpx's INFO request logger includes the full URL, including crtfc_key.
        record.msg = re.sub(r"(crtfc_key=)[^&\s\"']+", r"\1[REDACTED]", record.getMessage(), flags=re.I)
        record.args = ()
        return True


_filter = _KeyQueryFilter()
for _name in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy"):
    logging.getLogger(_name).addFilter(_filter)


class OpenDartClient:
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        self.settings, self.transport = settings, transport
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._http = httpx.AsyncClient(base_url=self.settings.opendart_base_url,
            timeout=self.settings.external_mcp_request_timeout_seconds, follow_redirects=False,
            trust_env=False, transport=self.transport)
        return self

    async def __aexit__(self, *args):
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def _get(self, path: str, params: dict[str, Any]) -> bytes:
        key = self.settings.opendart_api_key.get_secret_value()
        if len(key) != 40 or key.lower().startswith("change-me") or self._http is None:
            raise OpenDartError("OPENDART_AUTH_FAILED")
        try:
            async with self._http.stream("GET", path, params={"crtfc_key": key, **params}) as response:
                if response.status_code in (401, 403):
                    raise OpenDartError("OPENDART_AUTH_FAILED")
                if response.status_code == 429:
                    raise OpenDartError("OPENDART_RATE_LIMITED")
                if not response.is_success:
                    raise OpenDartError("OPENDART_UNAVAILABLE")
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self.settings.opendart_max_download_bytes:
                        raise OpenDartError("OPENDART_UNAVAILABLE")
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.TimeoutException:
            raise OpenDartError("OPENDART_TIMEOUT") from None
        except httpx.RequestError:
            raise OpenDartError("OPENDART_UNAVAILABLE") from None

    async def get_document(self, receipt_no: str) -> bytes:
        raw = await self._get("document.xml", {"rcept_no": receipt_no})
        if raw.startswith(b"PK"):
            return raw
        # The API returns XML status/message instead of a ZIP on application errors.
        try:
            root = etree.fromstring(raw, parser=etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False))
            status = root.findtext("status")
            if status is not None:
                check_status(status.strip())
        except (etree.XMLSyntaxError, ValueError):
            pass
        return raw  # Parser classifies non-ZIP/malformed document bytes.

    async def find_metadata(self, receipt_no: str) -> tuple[dict | None, str]:
        # Receipt prefix is a bounded search hint only. Returned dates/identity must
        # come from the exact rcept_no row, never from this inferred search window.
        try:
            hint = datetime.strptime(receipt_no[:8], "%Y%m%d").strftime("%Y%m%d")
        except ValueError:
            return None, "NOT_FOUND"
        for page in range(1, self.settings.opendart_metadata_max_pages + 1):
            raw = await self._get("list.json", {"bgn_de": hint, "end_de": hint,
                "last_reprt_at": "N", "page_count": 100, "page_no": page})
            try:
                result = json.loads(raw)
                if not isinstance(result, dict) or not isinstance(result.get("status"), str):
                    raise ValueError()
                check_status(result["status"], allow_empty=True)
                if result["status"] in ("013", "014"):
                    return None, "NOT_FOUND"
                rows, total_pages = result["list"], int(result["total_page"])
                if not isinstance(rows, list) or total_pages < 0:
                    raise ValueError()
                for row in rows:
                    if not isinstance(row, dict):
                        raise ValueError()
                    if row.get("rcept_no") == receipt_no:
                        return row, "FOUND"
                if page >= total_pages:
                    return None, "NOT_FOUND"
            except (ValueError, TypeError, KeyError):
                raise OpenDartError("OPENDART_UNAVAILABLE") from None
        return None, "SEARCH_LIMIT_REACHED"
