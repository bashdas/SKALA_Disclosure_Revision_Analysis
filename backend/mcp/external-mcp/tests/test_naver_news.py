import asyncio

import httpx
import pytest
from app.naver_news import NaverNews, article_url, parse_article, parse_headlines


def test_headline_title_and_naver_links_only():
    raw = """<html><a href="https://n.news.naver.com/mnews/article/001/0000000001?sid=101">한국은행 금리 결정</a>
    <a href="https://evil.example/article/1">외부 링크</a>
    <div><a href="https://n.news.naver.com/mnews/article/002/0000000002"><span>네이버뉴스</span><span>새 창 열림</span></a>
    <a data-heatmap-target=".tit" href="https://press.example/a">삼성중공업 계약 전망</a></div></html>""".encode()
    rows = parse_headlines(raw)
    assert len(rows) == 2
    assert rows[1]["title"] == "삼성중공업 계약 전망"
    assert all(set(row) == {"title", "url"} for row in rows)
    assert rows[0]["url"].endswith("/001/0000000001")


@pytest.mark.parametrize("url", ["http://n.news.naver.com/article/001/0000000001",
    "https://n.news.naver.com.evil.test/article/001/0000000001", "https://127.0.0.1/article/001/0000000001",
    "https://user@n.news.naver.com/article/001/0000000001", "https://n.news.naver.com:444/article/001/0000000001",
    "https://n.news.naver.com/mnews/article/comment/001/0000000001"])
def test_article_url_boundary(url):
    with pytest.raises(ValueError):
        article_url(url)


def test_body_and_timestamps_and_redirect_boundary():
    raw = '<h2 id="title_area">실적 뉴스</h2><span data-date-time="2026-10-23 09:00:00"></span><div id="dic_area">기사 본문<script>bad()</script></div>'.encode()
    article = parse_article(raw, "https://n.news.naver.com/article/001/0000000001")
    assert article["text"] == "기사 본문" and article["published_at"] == "2026-10-23T00:00:00+00:00"
    seen = []
    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})
    async def check():
        with pytest.raises(ValueError):
            await NaverNews(httpx.MockTransport(handler)).article(article["url"])
    asyncio.run(check())
    assert len(seen) == 1
