import asyncio
import html
import re
import time
from datetime import timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx


def clean_title(value):
    return " ".join(re.sub(r"<[^>]*>", "", html.unescape(value)).split())[:500]


def normalize_url(value):
    parts = urlsplit(value)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.port not in {None, 80, 443}
    ):
        raise ValueError("NEWS_URL_INVALID")
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}
    ]
    host = parts.hostname.lower()
    match = re.fullmatch(r"/(?:mnews/)?article/([0-9]{3})/([0-9]{8,12})", parts.path)
    if host in {"news.naver.com", "n.news.naver.com"} and match:
        return f"https://n.news.naver.com/mnews/article/{match[1]}/{match[2]}"
    return urlunsplit(
        (parts.scheme, host, parts.path or "/", urlencode(sorted(query)), "")
    )


class NaverNews:
    def __init__(self, settings, transport=None):
        self.settings, self.transport = settings, transport
        self.slots = asyncio.Semaphore(2)
        self.pace = asyncio.Lock()
        self.last_request = 0.0

    async def search(self, query, start=1, display=100):
        # 공개 API 조건은 저장과 AI 입력을 제한하므로 별도 허용 근거가 필요합니다.
        if not self.settings.news_usage_authorization.strip():
            return {"items": [], "error": "NEWS_USAGE_NOT_AUTHORIZED", "calls": 0}
        key = self.settings.naver_client_id.get_secret_value()
        secret = self.settings.naver_client_secret.get_secret_value()
        if not key or not secret:
            return {"items": [], "error": "NAVER_API_NOT_CONFIGURED", "calls": 0}
        if (
            not query.strip()
            or len(query) > 255
            or not 1 <= start <= 1000
            or not 1 <= display <= 100
        ):
            raise ValueError("INVALID_NEWS_QUERY")
        hub = self.settings.naver_api_provider == "hub"
        url = (
            "https://naverapihub.apigw.ntruss.com/search/v1/news"
            if hub
            else "https://openapi.naver.com/v1/search/news.json"
        )
        headers = (
            {"X-NCP-APIGW-API-KEY-ID": key, "X-NCP-APIGW-API-KEY": secret}
            if hub
            else {"X-Naver-Client-Id": key, "X-Naver-Client-Secret": secret}
        )
        async with (
            self.slots,
            httpx.AsyncClient(
                timeout=8,
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client,
        ):
            try:
                async with self.pace:
                    await asyncio.sleep(
                        max(0, 0.05 - (time.monotonic() - self.last_request))
                    )
                    self.last_request = time.monotonic()
                response = await client.get(
                    url,
                    headers=headers,
                    params={
                        "query": query,
                        "sort": "date",
                        "start": start,
                        "display": display,
                    },
                )
                if response.status_code != 200:
                    return {
                        "items": [],
                        "calls": 1,
                        "error": "NAVER_RATE_LIMIT"
                        if response.status_code == 429
                        else "NAVER_API_HTTP_" + str(response.status_code),
                    }
                payload = response.json()
                rows, invalid = [], 0
                for item in payload.get("items", []):
                    try:
                        title = clean_title(item["title"])
                        when = parsedate_to_datetime(item["pubDate"])
                        if not title or when.tzinfo is None:
                            raise ValueError("INVALID_NEWS_ROW")
                        rows.append(
                            {
                                "original_title": item["title"][:2000],
                                "title": title,
                                "url": normalize_url(item["link"]),
                                "original_url": normalize_url(item["originallink"])
                                if item.get("originallink")
                                else None,
                                "published_at": when.astimezone(
                                    timezone.utc
                                ).isoformat(),
                            }
                        )
                    except (KeyError, ValueError, TypeError):
                        invalid += 1
                return {
                    "items": rows,
                    "total": int(payload.get("total", 0)),
                    "start": start,
                    "raw_count": len(payload.get("items", [])),
                    "invalid": invalid,
                    "calls": 1,
                    "provider": "NAVER_SEARCH",
                    "title_only": True,
                }
            except (httpx.HTTPError, ValueError, TypeError):
                return {"items": [], "error": "NAVER_API_FAILED", "calls": 1}
