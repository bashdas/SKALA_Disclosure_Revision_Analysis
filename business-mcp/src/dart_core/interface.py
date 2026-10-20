"""Business MCP가 호출하는 dart_core 공개 인터페이스 (docs/05 §3).

F는 이 Protocol을 만족하는 구현(OpenDART + PostgreSQL)을 제공하고,
Business MCP는 `business_mcp.providers.get_dart_core()`에서 그 구현으로 교체합니다.
구현체: `business_mcp.mock.MockDartCore`(가상 데이터), `dart_core.live.LiveDartCore`(OpenDART + 파일 캐시).

오류는 `dart_core.status.DartError` 하위 클래스로 올립니다.
OpenDART 013(데이터 없음)은 예외가 아니라 빈 결과입니다.
"""

from datetime import date
from typing import Literal, Protocol

from dart_core.models import CompanyHit, FilingMeta, ParsedDocument

DataSource = Literal["db", "opendart", "mixed", "mock"]


class DartCore(Protocol):
    source: DataSource  # 응답 meta.source에 그대로 들어감

    async def resolve_company(self, query: str) -> tuple[CompanyHit | None, list[CompanyHit]]:
        """회사명·종목코드(6자리)·corp_code(8자리) → (확정 1건 | None, 후보 최대 10건).

        8자리 숫자 → corp_code, 6자리 숫자 → 종목코드, 그 밖에는 이름(정확 > 접두 > 부분,
        같은 단계에서는 상장사 우선). 정확 일치 1건이거나 전체 결과 1건이면 확정합니다.
        """
        ...

    async def list_filings(
        self,
        corp_code: str,
        date_from: date,
        date_to: date,
        *,
        last_reprt_at: Literal["Y", "N"] = "N",
        pblntf_ty: str | None = None,
        max_pages: int = 3,
    ) -> tuple[list[FilingMeta], int]:
        """기간 내 공시 목록 (최신순)과 OpenDART total_count. 013이면 ([], 0)."""
        ...

    async def find_filing(self, rcept_no: str, corp_code: str | None = None) -> FilingMeta | None:
        """접수번호 → 메타데이터 (filings 테이블 → list.json 일자 조회 우회). 없으면 None."""
        ...

    async def ingest_filing(self, rcept_no: str) -> ParsedDocument:
        """DB 확인 → 없으면 document.xml 다운로드·파싱·저장 후 반환.

        원문이 없으면 DartNotFound, 파싱 불가면 DocumentParseError.
        """
        ...
