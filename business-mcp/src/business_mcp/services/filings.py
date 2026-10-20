"""search_filings: 회사 해석 + 기간별 공시 목록 + 정정 식별 필드 (docs/05 §2-1)."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from business_mcp.errors import CompanyNotFound, InvalidArgument
from business_mcp.schemas import CompanyMatch, FilingSummary, Meta, SearchFilingsResult, dart_url
from dart_core.interface import DartCore
from dart_core.models import FilingMeta
from dart_core.titles import compare_key

KST = ZoneInfo("Asia/Seoul")
MAX_PAGES = 3  # page_count=100 기준 최대 300건


def to_summary(f: FilingMeta) -> FilingSummary:
    return FilingSummary(**f.model_dump(exclude={"pblntf_ty"}), dart_url=dart_url(f.rcept_no))


async def search_filings(
    dart: DartCore,
    corp: str,
    date_from: date | None = None,
    date_to: date | None = None,
    corrections_only: bool = False,
    keyword: str | None = None,
    pblntf_ty: str | None = None,
    limit: int = 50,
) -> SearchFilingsResult:
    corp = corp.strip()
    if not corp:
        raise InvalidArgument("corp는 비어 있을 수 없습니다.")
    if not 1 <= limit <= 100:
        raise InvalidArgument("limit은 1~100이어야 합니다.", limit=limit)
    date_to = date_to or datetime.now(KST).date()
    date_from = date_from or date_to - timedelta(days=365)
    if date_from > date_to:
        raise InvalidArgument("date_from이 date_to보다 늦습니다.",
                              date_from=date_from.isoformat(), date_to=date_to.isoformat())

    hit, candidates = await dart.resolve_company(corp)
    if hit is None:
        if not candidates:
            raise CompanyNotFound(f"'{corp}'에 해당하는 회사를 찾지 못했습니다.", corp=corp)
        return SearchFilingsResult(
            status="ambiguous_company", company=None,
            company_candidates=[CompanyMatch(**c.model_dump()) for c in candidates[:10]],
            filings=[], total_count=0, truncated=False, meta=Meta.build(dart.source),
        )

    rows, total_count = await dart.list_filings(
        hit.corp_code, date_from, date_to, last_reprt_at="N", pblntf_ty=pblntf_ty, max_pages=MAX_PAGES
    )
    warnings = []
    if len(rows) < total_count:
        warnings.append(f"OpenDART 결과 {total_count}건 중 최근 {len(rows)}건만 조회했습니다. 기간을 좁혀 주세요.")
    if corrections_only:
        rows = [f for f in rows if f.is_correction]
    if keyword and (kw := compare_key(keyword)):
        rows = [f for f in rows if kw in compare_key(f.base_report_nm)]

    return SearchFilingsResult(
        status="ok",
        company=CompanyMatch(**hit.model_dump()),
        company_candidates=[],
        filings=[to_summary(f) for f in rows[:limit]],
        total_count=total_count,
        truncated=len(rows) > limit or bool(warnings),
        meta=Meta.build(dart.source, warnings),
    )
