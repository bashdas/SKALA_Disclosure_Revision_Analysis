import httpx
import pytest
from app.main import app
from app.services import market
from fastapi.testclient import TestClient


def chart(symbol="^KS11", closes=None):
    return {
        "chart": {
            "result": [
                {
                    "meta": {"symbol": symbol},
                    "timestamp": [1700000000, 1700086400, 1700172800],
                    "indicators": {
                        "quote": [
                            {
                                "close": closes
                                if closes is not None
                                else [100, None, 110]
                            }
                        ]
                    },
                }
            ]
        }
    }


def test_daily_values_units_and_invalid_history():
    result = market.parse_chart(chart(), "^KS11", 1)
    assert result["series"] == [100, 110]
    assert result["previous_close"] == 100
    assert result["change_percent"] == pytest.approx(10)
    assert result["as_of"] == "2023-11-16T22:13:20+00:00"
    copper = market.parse_chart(chart("HG=F", [4, 4.5, 5]), "HG=F", 2204.6226218488)
    assert copper["value"] == pytest.approx(11023.113109244)
    assert copper["change_percent"] == pytest.approx((5 / 4.5 - 1) * 100)
    treasury = market.parse_chart(chart("^TNX", [4, 4.2, 4.25]), "^TNX", 1)
    assert treasury["change_bp"] == pytest.approx(5)
    assert (
        market.parse_chart(chart(closes=[0, None, 1]), "^KS11", 1)["change_percent"]
        is None
    )
    domestic = market.parse_domestic(
        {
            "code": "KPI200",
            "priceInfos": [
                {"localDate": "20261020", "closePrice": 800},
                {"localDate": "20261021", "closePrice": 808},
            ],
        },
        "KPI200",
    )
    assert domestic["value"] == 808 and domestic["change_percent"] == pytest.approx(1)
    assert domestic["as_of"] == "2026-10-20T15:00:00+00:00"
    for payload in [
        chart(closes=[None, float("nan"), 1]),
        chart("wrong"),
        chart(closes=[1]),
    ]:
        with pytest.raises(ValueError):
            market.parse_chart(payload, "^KS11", 1)


def test_partial_failure_cache_and_api(monkeypatch):
    calls = []
    original_client = httpx.Client

    def respond(request):
        symbol = request.url.path.rsplit("/", 1)[-1]
        calls.append(symbol)
        if symbol == "KOSDAQ":
            return httpx.Response(429)
        if symbol in market.DOMESTIC.values():
            return httpx.Response(
                200,
                json={
                    "code": symbol,
                    "priceInfos": [
                        {"localDate": "20261020", "closePrice": 100},
                        {"localDate": "20261021", "closePrice": 110},
                    ],
                },
            )
        return httpx.Response(200, json=chart(symbol))

    monkeypatch.setattr(
        market.httpx,
        "Client",
        lambda **kw: original_client(transport=httpx.MockTransport(respond), **kw),
    )
    source = market.MarketData()
    snapshot = source.snapshot()
    assert len(snapshot["items"]) == len(calls) == 12
    missing = next(q for q in snapshot["items"] if q["name"] == "KOSDAQ")
    assert (
        missing["status"] == "unavailable"
        and missing["value"] is None
        and missing["series"] == []
    )
    assert snapshot is source.snapshot() and len(calls) == 12
    source._expires = 0
    assert len(source.snapshot()["items"]) == 12 and len(calls) == 24
    monkeypatch.setattr(market.market_data, "snapshot", lambda: snapshot)
    response = TestClient(app).get("/api/v1/market/indices")
    assert response.status_code == 200 and response.json() == snapshot


def test_network_failure_does_not_fabricate_values():
    def fail(request):
        raise httpx.ConnectError("unavailable", request=request)

    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        row = market.MarketData()._fetch(client, "KOSPI")
    assert row["status"] == "unavailable"
    assert row["value"] is None and row["as_of"] is None and row["series"] == []


def test_stock_quotes_units_encoding_cache_and_validation(monkeypatch):
    import json

    calls = []
    original = httpx.Client

    def respond(request):
        calls.append(request)
        payload = {
            "resultCode": "success",
            "result": {
                "areas": [
                    {
                        "datas": [
                            {
                                "cd": "060310",
                                "nm": "삼에스",
                                "nv": 90,
                                "sv": 100,
                                "aa": 123456789,
                                "countOfListedStock": 1000,
                            },
                            {"cd": "005930", "nv": 0},
                            {"cd": "999999", "nv": 100},
                        ]
                    }
                ]
            },
        }
        return httpx.Response(
            200,
            content=json.dumps(payload, ensure_ascii=False).encode("euc-kr"),
            headers={"content-type": "text/plain;charset=EUC-KR"},
        )

    monkeypatch.setattr(
        market.httpx,
        "Client",
        lambda **kw: original(transport=httpx.MockTransport(respond), **kw),
    )
    market.stock_quotes.cache_clear()
    client = TestClient(app)
    result = client.get("/api/v1/market/stocks?codes=060310,005930").json()
    assert set(result["items"]) == {"060310"}
    quote = result["items"]["060310"]
    assert quote["changePercent"] == pytest.approx(-10)
    assert quote["tradingValue"] == 123456789
    assert quote["marketCap"] == 90000
    assert client.get("/api/v1/market/stocks?codes=005930,060310").json() == result
    assert len(calls) == 1
    for codes in ["", "AAPL", "005930,https://example.com", ",".join(["005930"] * 51)]:
        assert (
            client.get("/api/v1/market/stocks", params={"codes": codes}).status_code
            == 422
        )
    market.stock_quotes.cache_clear()

    def fail(request):
        raise httpx.ConnectError("offline", request=request)

    monkeypatch.setattr(
        market.httpx,
        "Client",
        lambda **kw: original(transport=httpx.MockTransport(fail), **kw),
    )
    assert client.get("/api/v1/market/stocks?codes=005930").status_code == 502


def test_sector_provider_mapping_and_missing_classification(monkeypatch):
    original = httpx.Client
    calls = []

    def respond(request):
        calls.append(request.url.path)
        if "/stocks/industry/" in request.url.path:
            return httpx.Response(
                200, json={"groupInfo": {"no": 278, "name": "반도체와반도체장비"}}
            )
        code = request.url.path.split("/")[-2]
        return httpx.Response(
            200,
            json={
                "itemCode": code,
                "industryCode": "278" if code == "005930" else None,
            },
        )

    monkeypatch.setattr(
        market.httpx,
        "Client",
        lambda **kw: original(transport=httpx.MockTransport(respond), **kw),
    )
    market.stock_sector.cache_clear()
    market.industry_name.cache_clear()
    assert market.stock_sector("005930", 1) == {
        "sector": "반도체와반도체장비",
        "status": "available",
    }
    assert market.stock_sector("005930", 1)["sector"] == "반도체와반도체장비"
    assert len(calls) == 2
    assert market.stock_sector("900010", 1) == {"sector": None, "status": "unavailable"}
    assert TestClient(app).get("/api/v1/market/sectors?codes=bad").status_code == 422
    market.stock_sector.cache_clear()
    market.industry_name.cache_clear()
