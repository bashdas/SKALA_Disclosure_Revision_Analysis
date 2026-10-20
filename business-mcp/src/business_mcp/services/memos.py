"""get_analysis_memo: ID·기업·인용 공시로 메모와 버전 정확 조회 (docs/05 §2-4)."""

import re
from typing import Protocol
from uuid import UUID

from business_mcp.errors import InvalidArgument, MemoNotFound
from business_mcp.schemas import AnalysisMemo, AnalysisMemoResult, Meta
from dart_core.interface import DataSource


class MemoRepository(Protocol):
    """메모 저장소. PostgreSQL 구현(analysis_memos + memo_versions)이 이 Protocol을 따르면 됩니다."""

    source: DataSource

    async def get_memo(self, memo_id: str, version: int | None = None) -> AnalysisMemo | None:
        """version=None이면 최신 버전. 메모나 해당 버전이 없으면 None."""
        ...

    async def list_memos(self, corp_code: str) -> list[AnalysisMemo]:
        """회사의 메모 전체 (각 메모의 최신 버전, updated_at 최신순)."""
        ...


def _cites(memo: AnalysisMemo, rcept_no: str) -> bool:
    return rcept_no in memo.source_rcept_nos or any(rcept_no in s.cited_rcept_nos for s in memo.sections or [])


async def get_analysis_memo(
    repo: MemoRepository,
    memo_id: str | None = None,
    corp_code: str | None = None,
    source_rcept_no: str | None = None,
    version: int | None = None,
    include_sections: bool = True,
) -> AnalysisMemoResult:
    if memo_id is None and corp_code is None:
        raise InvalidArgument("memo_id 또는 corp_code 중 하나는 필요합니다.")
    if memo_id is not None:
        try:
            memo_id = str(UUID(memo_id))
        except ValueError:
            raise InvalidArgument("memo_id는 UUID 형식이어야 합니다.", memo_id=memo_id) from None
    if corp_code is not None and not re.fullmatch(r"\d{8}", corp_code):
        raise InvalidArgument("corp_code는 8자리 숫자여야 합니다.", corp_code=corp_code)
    if source_rcept_no is not None and not re.fullmatch(r"\d{14}", source_rcept_no):
        raise InvalidArgument("source_rcept_no는 14자리 숫자여야 합니다.", source_rcept_no=source_rcept_no)
    if version is not None and (memo_id is None or version < 1):
        raise InvalidArgument("version은 memo_id와 함께 1 이상으로만 지정할 수 있습니다.", version=version)

    if memo_id is not None:
        memo = await repo.get_memo(memo_id, version)
        if memo is None:
            raise MemoNotFound("메모를 찾을 수 없습니다.", memo_id=memo_id, version=version)
        if corp_code is not None and memo.corp_code != corp_code:
            raise InvalidArgument("memo_id의 회사가 corp_code와 다릅니다.", memo_id=memo_id, corp_code=corp_code)
        memos = [memo]
    else:
        memos = await repo.list_memos(corp_code)

    if source_rcept_no is not None:
        memos = [m for m in memos if _cites(m, source_rcept_no)]
    if not include_sections:
        memos = [m.model_copy(update={"sections": None}) for m in memos]
    return AnalysisMemoResult(memos=memos, meta=Meta.build(repo.source))
