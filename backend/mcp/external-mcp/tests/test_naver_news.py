import asyncio

import httpx
import pytest
from app.config import Settings
from app.naver_news import NaverNews, clean_title, normalize_url


def test_title_and_distinct_url_normalization():
    assert clean_title("<b>테스트</b> &amp; 산업 뉴스") == "테스트 & 산업 뉴스"
    assert normalize_url("https://n.news.naver.com/mnews/article/001/0000000001?utm_source=x") == "https://n.news.naver.com/mnews/article/001/0000000001"
    assert normalize_url("https://publisher.example/news?id=1") != normalize_url("https://publisher.example/news?id=2")
    for value in ["javascript:alert(1)", "https://user:pass@example.com/x", "file:///tmp/x"]:
        with pytest.raises(ValueError):
            normalize_url(value)


@pytest.mark.parametrize("provider", ["hub", "legacy"])
def test_official_api_only_titles_no_body_requests(provider):
    calls = []
    def handle(request):
        calls.append(request)
        assert request.url.host in {"naverapihub.apigw.ntruss.com", "openapi.naver.com"}
        assert request.url.params["sort"] == "date"
        assert ("X-NCP-APIGW-API-KEY" if provider == "hub" else "X-Naver-Client-Secret") in request.headers
        return httpx.Response(200, json={"total": 1, "items": [{"title": "<b>가상기업</b> 뉴스",
            "link": "https://publisher.example/news/1", "originallink": "https://publisher.example/news/1",
            "pubDate": "Fri, 23 Oct 2026 09:00:00 +0900", "description": "이 본문은 저장하지 않습니다."}]})
    settings = Settings(naver_api_provider=provider, naver_client_id="synthetic-id", naver_client_secret="synthetic-secret",
                        news_usage_authorization="SYNTHETIC_TEST_ONLY")
    result = asyncio.run(NaverNews(settings, httpx.MockTransport(handle)).search("가상기업"))
    assert len(calls) == 1 and result["items"][0]["title"] == "가상기업 뉴스"
    assert result["items"][0]["published_at"] == "2026-10-23T00:00:00+00:00"
    assert all(k not in result["items"][0] for k in ["text", "description", "body"])


def test_missing_permission_key_and_rate_limit():
    def no_network(request):
        pytest.fail("요청하면 안 됩니다.")
    result = asyncio.run(NaverNews(Settings(), httpx.MockTransport(no_network)).search("가상기업"))
    assert result["error"] == "NEWS_USAGE_NOT_AUTHORIZED"
    result = asyncio.run(NaverNews(Settings(news_usage_authorization="SYNTHETIC_TEST_ONLY"), httpx.MockTransport(no_network)).search("가상기업"))
    assert result["error"] == "NAVER_API_NOT_CONFIGURED"
    settings = Settings(news_usage_authorization="SYNTHETIC_TEST_ONLY", naver_client_id="synthetic", naver_client_secret="synthetic")
    result = asyncio.run(NaverNews(settings, httpx.MockTransport(lambda _: httpx.Response(429))).search("가상기업"))
    assert result["error"] == "NAVER_RATE_LIMIT" and result["calls"] == 1
