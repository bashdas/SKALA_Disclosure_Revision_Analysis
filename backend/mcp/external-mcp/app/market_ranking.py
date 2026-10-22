"""코스피·코스닥 시가총액을 묶음 조회하고 페이지 간 같은 순위를 유지합니다."""
import asyncio
from collections import OrderedDict
from math import ceil
import re
import time
from uuid import uuid4

import httpx

from app.errors import OpenDartError


class MarketRanking:
    def __init__(self, transport=None):
        self.transport = transport
        self.lock = asyncio.Lock()
        self.snapshots: OrderedDict[str, dict[str, int]] = OrderedDict()
        self.loaded_at = 0.0

    async def get(self, snapshot: str = "") -> tuple[str, dict[str, int]]:
        async with self.lock:
            if snapshot:
                if snapshot not in self.snapshots:
                    raise OpenDartError("MARKET_RANKING_EXPIRED")
                return snapshot, self.snapshots[snapshot]
            if self.snapshots and time.monotonic() - self.loaded_at < 300:
                key = next(reversed(self.snapshots))
                return key, self.snapshots[key]
            try:
                values = await self.fetch()
            except (httpx.HTTPError, ValueError, TypeError, KeyError, OverflowError):
                # 순위 조회 실패를 무작위 목록이나 일부 시장의 순위로 대체하지 않습니다.
                raise OpenDartError("MARKET_RANKING_UNAVAILABLE") from None
            key = uuid4().hex
            self.snapshots[key] = values
            self.loaded_at = time.monotonic()
            # 이전 방문의 추가 페이지는 갱신 전 순위를 사용합니다. 최근 12개 순위를 보관합니다.
            if len(self.snapshots) > 12:
                self.snapshots.popitem(last=False)
            return key, values

    async def fetch(self) -> dict[str, int]:
        semaphore = asyncio.Semaphore(6)
        async with httpx.AsyncClient(
            timeout=8, trust_env=False, transport=self.transport,
            headers={"User-Agent": "Mozilla/5.0"},
        ) as client:
            async def page(market, number):
                async with semaphore:
                    response = await client.get(
                        f"https://m.stock.naver.com/api/stocks/marketValue/{market}",
                        params={"page": number, "pageSize": 100},
                    )
                    response.raise_for_status()
                    data = response.json()
                if (data["stockListCategoryType"] != market
                    or data["page"] != number or data["pageSize"] != 100
                    or not isinstance(data["stocks"], list)
                    or type(data["totalCount"]) is not int
                    or not 0 < data["totalCount"] <= 10000):
                    raise ValueError("Invalid market ranking page")
                return data

            async def market_rows(market):
                first = await page(market, 1)
                remaining = await asyncio.gather(*(
                    page(market, number)
                    for number in range(2, ceil(first["totalCount"] / 100) + 1)
                ))
                rows = [row for data in [first, *remaining] for row in data["stocks"]]
                if len(rows) != first["totalCount"]:
                    raise ValueError("Incomplete market ranking")
                return rows

            markets = await asyncio.gather(market_rows("KOSPI"), market_rows("KOSDAQ"))
        values = {}
        for rows in markets:
            for row in rows:
                code = row["itemCode"]
                if not re.fullmatch(r"[0-9]{6}", code):
                    continue
                # marketValueRaw는 원 단위, 기존 marketValue는 억 원 단위입니다.
                raw = row.get("marketValueRaw")
                if raw is None:
                    raw = str(row["marketValue"]).replace(",", "")
                    multiplier = 100_000_000
                else:
                    raw = str(raw)
                    multiplier = 1
                if not re.fullmatch(r"[0-9]+", raw):
                    continue
                value = int(raw) * multiplier
                if value > 0:
                    values[code] = value
        if not values:
            raise ValueError("Empty market ranking")
        return values
