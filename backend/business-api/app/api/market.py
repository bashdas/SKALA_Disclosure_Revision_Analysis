"""공개 시장 지표를 제공합니다."""

from concurrent.futures import ThreadPoolExecutor
from time import monotonic

import httpx
from fastapi import APIRouter, HTTPException, Query

from app.services.market import market_data, stock_quotes, stock_sector

router = APIRouter(prefix="/api/v1/market", tags=["market"])


@router.get("/sectors")
def sectors(codes: str = Query(pattern=r"^[0-9]{6}(,[0-9]{6}){0,49}$")) -> dict:
    unique = sorted(set(codes.split(",")))
    period = int(monotonic() // 300)
    with ThreadPoolExecutor(max_workers=6) as pool:
        items = list(pool.map(lambda code: stock_sector(code, period), unique))
    return {"items": dict(zip(unique, items))}


@router.get("/indices")
def indices() -> dict:
    return market_data.snapshot()


@router.get("/stocks")
def stocks(codes: str = Query(pattern=r"^[0-9]{6}(,[0-9]{6}){0,49}$")) -> dict:
    try:
        return stock_quotes(
            tuple(sorted(set(codes.split(",")))), int(monotonic() // 60)
        )
    except (httpx.HTTPError, ValueError, KeyError, TypeError, OverflowError) as exc:
        raise HTTPException(
            status_code=502, detail="종목 시세를 조회하지 못했습니다."
        ) from exc
