"""OpenDART 공시 검색과 사용자별 관심 기업을 제공합니다."""
from datetime import date, datetime
from zoneinfo import ZoneInfo
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, Path
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.api.dependencies import get_disclosure_source, require_roles
from app.core.database import get_db
from app.domain.disclosure_exceptions import DisclosureError
from app.models import CompanyFavorite
from app.models.enums import UserRole
from app.schemas.auth import CurrentUser
from app.schemas.filing import FavoriteRequest, FavoriteResponse
from app.services.disclosure_source import DisclosureSource

router = APIRouter(prefix="/api/v1", tags=["disclosures"])
Reader = Annotated[CurrentUser, Depends(require_roles(UserRole.RA, UserRole.ANALYST))]
Source = Annotated[DisclosureSource, Depends(get_disclosure_source)]
Database = Annotated[Session, Depends(get_db)]


@router.get("/disclosures/companies")
def search_companies(user: Reader, source: Source,
    query: Annotated[str, Query(max_length=100)] = "",
    offset: Annotated[int, Query(ge=0)] = 0,
    seed: Annotated[str, Query(max_length=100)] = "",
    sort: Literal["default", "name", "market_cap_desc", "market_cap_asc"] = "default",
    snapshot: Annotated[str, Query(max_length=32, pattern=r"^(?:[0-9a-f]{32})?$")] = "") -> dict:
    args = {"query": query, "offset": offset, "limit": 20, "seed": seed}
    if sort != "default":
        args["sort"] = sort
    if snapshot:
        args["snapshot"] = snapshot
    return source.call("opendart_search_companies", args)


@router.get("/disclosures")
def search_disclosures(user: Reader, source: Source, start_date: date | None = None, end_date: date | None = None,
    corp_code: Annotated[str | None, Query(pattern=r"^(?:[0-9]{8}|SEC:[0-9]{1,10})$")] = None,
    page: Annotated[int, Query(ge=1, le=10000)] = 1,
    query: Annotated[str, Query(max_length=100)] = "") -> dict:
    end_date = end_date or datetime.now(ZoneInfo("Asia/Seoul")).date()
    start_date = start_date or (date(1999, 1, 1) if corp_code else end_date)
    if start_date > end_date:
        raise DisclosureError("INVALID_SEARCH_RANGE", "시작일과 종료일을 확인해 주세요.", 422)
    return source.call("opendart_search_disclosures", {"corp_code": corp_code,
        "start_date": start_date.isoformat(), "end_date": end_date.isoformat(), "page": page, "query": query})


@router.get("/favorites", response_model=list[FavoriteResponse])
def favorites(user: Reader, db: Database,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0) -> list[FavoriteResponse]:
    rows = db.scalars(select(CompanyFavorite).where(CompanyFavorite.user_id == user.id)
        .order_by(CompanyFavorite.company_name, CompanyFavorite.id).limit(limit).offset(offset))
    return [FavoriteResponse.model_validate(row) for row in rows]


@router.post("/favorites", response_model=FavoriteResponse)
def add_favorite(request: FavoriteRequest, user: Reader, source: Source, db: Database) -> FavoriteResponse:
    # 이름과 종목코드는 외부에서 확인한 값으로만 저장합니다.
    result = source.call("opendart_search_companies", {"query": request.corp_code, "limit": 20, "offset": 0})
    company = next((row for row in result.get("items", []) if row.get("corp_code") == request.corp_code), None)
    if company is None:
        raise DisclosureError("COMPANY_NOT_FOUND", "OpenDART에서 회사를 찾지 못했습니다.", 404)
    try:
        command = insert(CompanyFavorite).values(user_id=user.id, corp_code=request.corp_code,
            company_name=company["company_name"], stock_code=company.get("stock_code", ""))
        row = db.scalar(command.on_conflict_do_update(constraint="uq_company_favorites_user_corp",
            set_={"company_name": company["company_name"]}).returning(CompanyFavorite))
        response = FavoriteResponse.model_validate(row)
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


@router.delete("/favorites/{corp_code}", status_code=204)
def remove_favorite(corp_code: Annotated[str, Path(pattern=r"^(?:[0-9]{8}|SEC:[0-9]{1,10})$")], user: Reader, db: Database) -> Response:
    try:
        db.execute(delete(CompanyFavorite).where(CompanyFavorite.user_id == user.id, CompanyFavorite.corp_code == corp_code))
        db.commit()
        return Response(status_code=204)
    except Exception:
        db.rollback()
        raise
