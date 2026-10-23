import asyncio
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

import httpx
from lxml import etree


def article_url(value):
    parts = urlsplit(value)
    match = re.fullmatch(r"/(?:mnews/)?article/([0-9]{3})/([0-9]{8,12})", parts.path)
    if (parts.scheme != "https" or parts.hostname not in {"news.naver.com", "n.news.naver.com"}
            or parts.username or parts.password or parts.port not in {None, 443} or not match):
        raise ValueError("INVALID_NAVER_NEWS_URL")
    return f"https://n.news.naver.com/mnews/article/{match[1]}/{match[2]}"


def parse_headlines(raw):
    root = etree.fromstring(raw, etree.HTMLParser(no_network=True, encoding="utf-8"))
    result = {}
    for link in root.xpath('//a[@href]'):
        try:
            url = article_url(link.get("href"))
        except ValueError:
            continue
        title = " ".join(" ".join(link.itertext()).split()).removesuffix("새 창 열림").strip()
        if not title or title in {"네이버뉴스", "새 창 열림"}:
            title = ""
            for parent in link.iterancestors():
                titles = parent.xpath('.//a[@data-heatmap-target=".tit"]')
                if titles:
                    title = " ".join(" ".join(titles[0].itertext()).split()).removesuffix("새 창 열림").strip()
                    break
                if parent.tag in {"body", "html"}:
                    break
        if title and len(title) >= 5:
            result[url] = {"title": title[:500], "url": url}
    return list(result.values())


def parse_article(raw, url):
    root = etree.fromstring(raw, etree.HTMLParser(no_network=True, encoding="utf-8"))
    bodies = root.xpath('//*[@id="dic_area"]')
    if not bodies:
        raise ValueError("NAVER_ARTICLE_BODY_UNAVAILABLE")
    for node in bodies[0].xpath('.//script | .//style | .//iframe'):
        node.getparent().remove(node)
    text = " ".join("".join(bodies[0].itertext()).split())
    if not text:
        raise ValueError("NAVER_ARTICLE_BODY_UNAVAILABLE")
    titles = root.xpath('//*[@id="title_area"]//text()')
    published = root.xpath('//*[@data-date-time]/@data-date-time')
    modified = root.xpath('//*[contains(@class,"_ARTICLE_MODIFY_DATE_TIME")]/@data-modify-date-time')
    def timestamp(values):
        if not values:
            return None
        value = datetime.fromisoformat(values[0])
        if value.tzinfo is None:
            from zoneinfo import ZoneInfo
            value = value.replace(tzinfo=ZoneInfo("Asia/Seoul"))
        return value.astimezone(timezone.utc).isoformat()
    return {"url": article_url(url), "title": " ".join(titles).strip(), "text": text[:12000],
            "published_at": timestamp(published), "modified_at": timestamp(modified),
            "truncated": len(text) > 12000}


class NaverNews:
    def __init__(self, transport=None):
        self.transport = transport
        self.slots = asyncio.Semaphore(3)

    async def fetch(self, url, *, params=None, article=False):
        async with self.slots, httpx.AsyncClient(timeout=8, follow_redirects=False,
                trust_env=False, transport=self.transport, headers={"User-Agent": "DisclosureResearch/1.0"}) as client:
            for _ in range(3):
                if article:
                    url = article_url(url)
                async with client.stream("GET", url, params=params) as response:
                    if article and response.is_redirect:
                        url = article_url(urljoin(url, response.headers["location"]))
                        params = None
                        continue
                    response.raise_for_status()
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 2 * 1024 * 1024:
                            raise ValueError("NAVER_NEWS_SIZE_LIMIT")
                        chunks.append(chunk)
                    return b"".join(chunks)
            raise ValueError("NAVER_NEWS_REDIRECT_LIMIT")

    async def headlines(self, company_name=""):
        if company_name:
            pages = [("https://search.naver.com/search.naver",
                      {"where": "news", "query": company_name, "sort": "1"})]
        else:
            pages = [(f"https://news.naver.com/section/{section}", None) for section in (101, 104)]
        rows = {}
        errors = []
        for url, params in pages:
            try:
                raw = await self.fetch(url, params=params)
                found = parse_headlines(raw)
                if not found:
                    errors.append("NAVER_HEADLINES_EMPTY")
                for item in found:
                    rows[item["url"]] = item
            except (httpx.HTTPError, ValueError, etree.LxmlError) as error:
                errors.append(type(error).__name__)
        return {"items": list(rows.values()), "limitations": errors}

    async def article(self, url):
        url = article_url(url)
        return parse_article(await self.fetch(url, article=True), url)
