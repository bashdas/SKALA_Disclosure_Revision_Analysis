"""시장 지표의 최근 한 달 일별 시세를 조회합니다."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import lru_cache
from math import isfinite
from threading import Lock
from time import monotonic
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

# 구리 선물의 파운드당 가격을 화면의 미터톤당 가격으로 환산합니다.
INSTRUMENTS = {
    "KOSPI": ("^KS11", 1),
    "KOSDAQ": ("^KQ11", 1),
    "KOSPI 200": ("^KS200", 1),
    "S&P 500": ("^GSPC", 1),
    "NASDAQ": ("^IXIC", 1),
    "NIKKEI 225": ("^N225", 1),
    "USD/KRW": ("KRW=X", 1),
    "DXY": ("DX-Y.NYB", 1),
    "미국채 10Y": ("^TNX", 1),
    "WTI": ("CL=F", 1),
    "GOLD": ("GC=F", 1),
    "COPPER": ("HG=F", 2204.6226218488),
}
DOMESTIC = {"KOSPI": "KOSPI", "KOSDAQ": "KOSDAQ", "KOSPI 200": "KPI200"}


def finite(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(value)
    )


def parse_chart(payload: dict, symbol: str, factor: float) -> dict:
    result = payload["chart"]["result"][0]
    if result["meta"]["symbol"] != symbol:
        raise ValueError("Unexpected market symbol")
    timestamps = result["timestamp"]
    closes = result["indicators"]["quote"][0]["close"]
    if len(timestamps) != len(closes):
        raise ValueError("Invalid market series")
    # 휴장일과 미수신 값은 0으로 채우지 않고 유효한 관측값만 보존합니다.
    points = sorted(
        (timestamp, close * factor)
        for timestamp, close in zip(timestamps, closes)
        if finite(timestamp) and timestamp > 0 and finite(close)
    )
    return summarize(points, symbol == "^TNX")


def parse_domestic(payload: dict, code: str) -> dict:
    if payload["code"] != code:
        raise ValueError("Unexpected market code")
    points = sorted(
        (
            datetime.strptime(row["localDate"], "%Y%m%d")
            .replace(tzinfo=ZoneInfo("Asia/Seoul"))
            .timestamp(),
            row["closePrice"],
        )
        for row in payload["priceInfos"]
        if finite(row.get("closePrice"))
    )
    return summarize(points)


def summarize(points: list[tuple], treasury: bool = False) -> dict:
    if len(points) < 2:
        raise ValueError("Insufficient market history")
    previous, value = points[-2][1], points[-1][1]
    return {
        "value": value,
        "previous_close": previous,
        "change_percent": (value / previous - 1) * 100 if previous else None,
        "change_bp": (value - previous) * 100 if treasury else None,
        "as_of": datetime.fromtimestamp(points[-1][0], UTC).isoformat(),
        "series": [value for _, value in points],
        "status": "available",
    }


class MarketData:
    def __init__(self):
        self._lock = Lock()
        self._expires = 0
        self._snapshot = None

    def _fetch(self, client: httpx.Client, name: str) -> dict:
        symbol, factor = INSTRUMENTS[name]
        try:
            # 국내 지수는 월간 이력을 제공하는 네이버의 일별 자료를 사용합니다.
            if name in DOMESTIC:
                response = client.get(
                    f"https://api.stock.naver.com/chart/domestic/index/{DOMESTIC[name]}",
                    params={"periodType": "month"},
                )
            else:
                response = client.get(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}",
                    params={"interval": "1d", "range": "1mo"},
                )
            response.raise_for_status()
            data = (
                parse_domestic(response.json(), DOMESTIC[name])
                if name in DOMESTIC
                else parse_chart(response.json(), symbol, factor)
            )
            return {"name": name, **data}
        except (
            httpx.HTTPError,
            ValueError,
            TypeError,
            KeyError,
            IndexError,
            OverflowError,
            OSError,
        ):
            return {
                "name": name,
                "value": None,
                "previous_close": None,
                "change_percent": None,
                "change_bp": None,
                "as_of": None,
                "series": [],
                "status": "unavailable",
            }

    def snapshot(self) -> dict:
        # 1분 캐시로 화면 갱신마다 외부 요청 12개가 반복되는 것을 막습니다.
        with self._lock:
            if self._snapshot is not None and monotonic() < self._expires:
                return self._snapshot
            with (
                httpx.Client(
                    timeout=8, headers={"User-Agent": "Mozilla/5.0"}
                ) as client,
                ThreadPoolExecutor(max_workers=6) as pool,
            ):
                items = list(
                    pool.map(lambda name: self._fetch(client, name), INSTRUMENTS)
                )
            self._snapshot = {
                "source": "NAVER Finance, Yahoo Finance",
                "interval": "1d",
                "range": "1mo",
                "delayed": True,
                "fetched_at": datetime.now(UTC).isoformat(),
                "items": items,
            }
            self._expires = monotonic() + 60
            return self._snapshot


market_data = MarketData()


@lru_cache(maxsize=512)
def industry_name(industry: str, hour: int) -> str:
    with httpx.Client(timeout=8) as client:
        response = client.get(
            f"https://m.stock.naver.com/api/stocks/industry/{industry}"
        )
        response.raise_for_status()
        group = response.json()["groupInfo"]
    if str(group["no"]) != industry:
        raise ValueError("Unexpected industry")
    if not isinstance(group["name"], str) or not group["name"].strip():
        raise ValueError("Missing industry name")
    return group["name"]


@lru_cache(maxsize=4096)
def stock_sector(code: str, period: int) -> dict:
    try:
        with httpx.Client(timeout=8) as client:
            response = client.get(
                f"https://m.stock.naver.com/api/stock/{code}/integration"
            )
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("Invalid sector response")
        if payload.get("itemCode") != code:
            return {"sector": None, "status": "unavailable"}
        industry = str(payload.get("industryCode", ""))
        if not industry.isascii() or not industry.isdigit():
            return {"sector": None, "status": "unavailable"}
        return {"sector": industry_name(industry, period // 12), "status": "available"}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return {"sector": None, "status": "error"}


@lru_cache(maxsize=256)
def stock_quotes(codes: tuple[str, ...], minute: int) -> dict:
    """국내 종목 묶음을 1분 단위로 보관합니다."""
    with httpx.Client(timeout=8, headers={"User-Agent": "Mozilla/5.0"}) as client:
        response = client.get(
            "https://polling.finance.naver.com/api/realtime",
            params={"query": "SERVICE_ITEM:" + ",".join(codes)},
        )
        response.raise_for_status()
        payload = json.loads(response.text)
    if payload.get("resultCode") != "success":
        raise ValueError("Stock quote request failed")
    items = {}
    for area in payload["result"]["areas"]:
        for row in area["datas"]:
            code = row.get("cd")
            if code not in codes:
                continue
            price, previous = row.get("nv"), row.get("sv")
            shares, traded = row.get("countOfListedStock"), row.get("aa")
            if not finite(price) or price <= 0:
                continue
            items[code] = {
                "price": price,
                "openPrice": row.get("ov") if finite(row.get("ov")) and row["ov"] > 0 else None,
                "highPrice": row.get("hv") if finite(row.get("hv")) and row["hv"] > 0 else None,
                "lowPrice": row.get("lv") if finite(row.get("lv")) and row["lv"] > 0 else None,
                "volume": row.get("aq") if finite(row.get("aq")) and row["aq"] >= 0 else None,
                "changePercent": (price / previous - 1) * 100
                if finite(previous) and previous > 0
                else None,
                "tradingValue": traded if finite(traded) and traded >= 0 else None,
                "marketCap": price * shares if finite(shares) and shares > 0 else None,
            }
    return {
        "source": "NAVER Finance (KRX)",
        "fetched_at": datetime.now(UTC).isoformat(),
        "items": items,
    }


@lru_cache(maxsize=256)
def stock_history(code: str, minute: int) -> dict:
    with httpx.Client(timeout=8) as client:
        response = client.get(
            f"https://api.stock.naver.com/chart/domestic/item/{code}",
            params={"periodType": "month"},
        )
        response.raise_for_status()
        payload = response.json()
    data = parse_domestic(payload, code)
    dates = sorted(
        row["localDate"]
        for row in payload["priceInfos"]
        if finite(row.get("closePrice"))
    )
    return {**data, "start_date": dates[0], "end_date": dates[-1]}
