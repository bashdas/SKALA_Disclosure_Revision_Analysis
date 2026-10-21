"""Google Scholar search through SerpApi; no full-text fetching or LLM analysis."""
from datetime import datetime, timezone
import logging
import re
from urllib.parse import urlsplit

import httpx


class ScholarError(Exception):
    MESSAGES = {
        "SCHOLAR_AUTH_FAILED": "Scholar search key is missing or invalid",
        "SCHOLAR_RATE_LIMITED": "Scholar search request limit exceeded",
        "SCHOLAR_TIMEOUT": "Scholar search timed out",
        "SCHOLAR_UNAVAILABLE": "Scholar search provider is unavailable",
        "SCHOLAR_INVALID_RESPONSE": "Scholar search provider returned an invalid response",
    }

    def __init__(self, code):
        self.code = code
        super().__init__(self.MESSAGES[code])


class _ScholarKeyFilter(logging.Filter):
    def filter(self, record):
        record.msg = re.sub(r"(api_key=)[^&\s\"']+", r"\1[REDACTED]", record.getMessage(), flags=re.I)
        record.args = ()
        return True


for _name in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy"):
    logging.getLogger(_name).addFilter(_ScholarKeyFilter())


def _url(value):
    if not isinstance(value, str):
        return None
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        return None
    # Do not expose provider credential-bearing URLs from response metadata.
    if "api_key=" in value.lower():
        return None
    return value


class GoogleScholarClient:
    def __init__(self, settings, *, transport=None):
        self.settings, self.transport = settings, transport
        self.http = None

    async def __aenter__(self):
        self.http = httpx.AsyncClient(timeout=self.settings.external_mcp_request_timeout_seconds,
            transport=self.transport, trust_env=False, follow_redirects=False)
        return self

    async def __aexit__(self, *args):
        if self.http is not None:
            await self.http.aclose()
            self.http = None

    async def search(self, query, limit, year_from=None, year_to=None):
        key = self.settings.serpapi_api_key.get_secret_value()
        if not key or key.startswith("change-me") or self.http is None:
            raise ScholarError("SCHOLAR_AUTH_FAILED")
        params = {"engine": "google_scholar", "api_key": key, "q": query, "num": limit}
        if year_from is not None:
            params["as_ylo"] = year_from
        if year_to is not None:
            params["as_yhi"] = year_to
        try:
            async with self.http.stream("GET", "https://serpapi.com/search.json", params=params) as response:
                if response.status_code in (401, 403):
                    raise ScholarError("SCHOLAR_AUTH_FAILED")
                if response.status_code == 429:
                    raise ScholarError("SCHOLAR_RATE_LIMITED")
                if not response.is_success:
                    raise ScholarError("SCHOLAR_UNAVAILABLE")
                data, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 2 * 1024 * 1024:
                        raise ScholarError("SCHOLAR_INVALID_RESPONSE")
                    data.append(chunk)
                import json
                body = json.loads(b"".join(data))
            if not isinstance(body, dict):
                raise ValueError()
            if body.get("error"):
                # Provider messages may echo input/key; never forward raw errors.
                raise ScholarError("SCHOLAR_UNAVAILABLE")
            rows = body.get("organic_results")
            if rows is None:
                state = body.get("search_information", {}).get("organic_results_state", "")
                if isinstance(state, str) and state.startswith("Fully empty"):
                    rows = []
                else:
                    raise ValueError()
            if not isinstance(rows, list):
                raise ValueError()
            results = []
            now = datetime.now(timezone.utc).isoformat()
            for row in rows[:limit]:
                if not isinstance(row, dict) or not isinstance(row.get("title"), str):
                    raise ValueError()
                publication = row.get("publication_info") or {}
                if not isinstance(publication, dict):
                    raise ValueError()
                authors = publication.get("authors") or []
                if not isinstance(authors, list):
                    raise ValueError()
                link = _url(row.get("link"))
                results.append({"document_id": row.get("result_id"), "title": row["title"],
                    "url": link, "snippet": row.get("snippet"),
                    "authors": [a["name"] for a in authors if isinstance(a, dict) and isinstance(a.get("name"), str)],
                    "publication_info": publication.get("summary"),
                    "source": {"provider": "SERPAPI", "source_type": "ACADEMIC_SEARCH",
                        "search_engine": "GOOGLE_SCHOLAR", "identifier": row.get("result_id"),
                        "original_location": link, "retrieved_at": now, "published_at": None}})
            return {"query": query, "results": results}
        except httpx.TimeoutException:
            raise ScholarError("SCHOLAR_TIMEOUT") from None
        except httpx.RequestError:
            raise ScholarError("SCHOLAR_UNAVAILABLE") from None
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ScholarError("SCHOLAR_INVALID_RESPONSE") from None
