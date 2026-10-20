"""DartCore Protocol의 실데이터 구현 (OpenDART + 파일 캐시).

- resolve_company: CorpCodeIndex (corpCode.xml 캐시)
- list_filings: list.json, page_count=100, max_pages 상한, rcept_no 중복 제거, 최신순. total_count는 OpenDART 값 그대로
- find_filing: 메타 캐시 → (corp_code를 알면) 회사·일자 조회 → (모르면) 접수일 하루 전체 목록을 페이지 끝까지 조회.
  접수번호 앞 8자리 = 접수일 가정은 공개 검색 70여 건에서 성립을 확인했지만 공식 규칙은 아닙니다(docs/spike_notes.md).
  페이지 예산(find_max_pages) 때문에 끝까지 못 보면 '없음'이 아니라 FILING_NOT_FOUND(lookup_complete=false)로 구분합니다.
- ingest_filing: 파싱 캐시(parser_version·ZIP 해시 일치) → ZIP 캐시 → document.xml 다운로드. 같은 접수번호 동시 요청은 잠금으로 1회만.
응답 meta.source는 항상 "opendart"입니다(파일 캐시는 05 문서의 DB 저장소가 아니므로 "db"로 표시하지 않음).
"""

import asyncio
import logging
from datetime import date, datetime
from typing import Literal

from pydantic import ValidationError

from dart_core.client import DartClient
from dart_core.corp_codes import CorpCodeIndex
from dart_core.models import CompanyHit, FilingMeta, ParsedDocument
from dart_core.parsing.document import PARSER_VERSION, parse_zip
from dart_core.status import DartNotFound, DartUnavailable
from dart_core.store import FileStore
from dart_core.titles import to_filing_meta

logger = logging.getLogger(__name__)
PAGE_COUNT = 100


def _yyyymmdd(d: date) -> str:
    return d.strftime("%Y%m%d")


class LiveDartCore:
    source = "opendart"

    def __init__(self, client: DartClient, store: FileStore, corp_index: CorpCodeIndex, *, find_max_pages: int = 30):
        self.client = client
        self.store = store
        self.corp_index = corp_index
        self.find_max_pages = find_max_pages
        self._locks: dict[str, asyncio.Lock] = {}

    async def aclose(self) -> None:
        await self.client.aclose()

    async def resolve_company(self, query: str) -> tuple[CompanyHit | None, list[CompanyHit]]:
        return await self.corp_index.resolve(query)

    async def _pages(self, params: dict, max_pages: int, stop=None) -> tuple[list[dict], int, int, int]:
        """(행, total_count, 읽은 페이지, total_page). stop(rows)가 True면 중단."""
        rows: list[dict] = []
        total = total_page = 0
        page = 0
        while page < max_pages:
            page += 1
            data = await self.client.get_json("/api/list.json", {**params, "page_no": page, "page_count": PAGE_COUNT})
            if page == 1:
                total, total_page = int(data.get("total_count") or 0), int(data.get("total_page") or 0)
            batch = data.get("list") or []
            if not isinstance(batch, list):
                raise DartUnavailable(None, "list.json: list가 배열이 아님")
            rows.extend(batch)
            if (stop and stop(batch)) or page >= total_page or not batch:
                break
        return rows, total, page, total_page

    def _to_metas(self, rows: list[dict], pblntf_ty: str | None) -> list[FilingMeta]:
        metas: dict[str, FilingMeta] = {}
        for row in rows:
            try:
                m = to_filing_meta({**row, "pblntf_ty": row.get("pblntf_ty") or pblntf_ty})
            except (KeyError, ValueError, ValidationError):
                raise DartUnavailable(None, "list.json: 공시 행 형식이 예상과 다름") from None
            metas[m.rcept_no] = m
            self.store.put_meta(m)  # rm('정'·'철')은 바뀔 수 있어 목록에서 볼 때마다 갱신
        return sorted(metas.values(), key=lambda f: f.rcept_no, reverse=True)

    async def list_filings(
        self, corp_code: str, date_from: date, date_to: date, *, last_reprt_at: Literal["Y", "N"] = "N",
        pblntf_ty: str | None = None, max_pages: int = 3,
    ) -> tuple[list[FilingMeta], int]:
        params = {"corp_code": corp_code, "bgn_de": _yyyymmdd(date_from), "end_de": _yyyymmdd(date_to),
                  "last_reprt_at": last_reprt_at, "pblntf_ty": pblntf_ty, "sort": "date", "sort_mth": "desc"}
        rows, total, _, _ = await self._pages(params, max_pages)
        return self._to_metas(rows, pblntf_ty), total

    async def find_filing(self, rcept_no: str, corp_code: str | None = None) -> FilingMeta | None:
        if cached := self.store.get_meta(rcept_no):
            return cached
        try:
            day = datetime.strptime(rcept_no[:8], "%Y%m%d").date()
        except ValueError:
            return None  # 앞 8자리가 날짜가 아니면 일자 조회로 찾을 수 없음
        params = {"bgn_de": _yyyymmdd(day), "end_de": _yyyymmdd(day), "last_reprt_at": "N", "sort": "date",
                  "sort_mth": "desc"}
        if corp_code:
            params["corp_code"] = corp_code
        rows, _total, pages, total_page = await self._pages(
            params, self.find_max_pages, stop=lambda batch: any(r.get("rcept_no") == rcept_no for r in batch))
        found = [r for r in rows if r.get("rcept_no") == rcept_no]
        if found:
            return self._to_metas(found, None)[0]
        if pages < total_page:
            raise DartNotFound(
                None, f"접수일 {day.isoformat()} 목록 {total_page}페이지 중 {pages}페이지까지만 조회해 찾지 못했습니다.",
                rcept_no=rcept_no, lookup_complete=False, pages_scanned=pages, total_pages=total_page,
                hint="search_filings로 회사를 먼저 조회하면 메타데이터가 캐시되어 바로 찾습니다.",
            )
        return None

    async def ingest_filing(self, rcept_no: str) -> ParsedDocument:
        lock = self._locks.setdefault(rcept_no, asyncio.Lock())
        async with lock:
            # ZIP 캐시는 sha256 파일과 맞을 때만 씀(불일치 = 손상 → store가 지우고 None). 파싱 캐시는
            # parser_version과 ZIP 해시가 모두 맞을 때만 씀 → 파서 버전을 올리면 저장된 ZIP으로 다시 파싱.
            if cached := self.store.get_zip(rcept_no):
                data, digest = cached
                if doc := self.store.get_parsed(rcept_no, PARSER_VERSION, digest):
                    return doc
                doc = parse_zip(rcept_no, data)
                self.store.put_parsed(doc, digest)
                return doc
            data = await self.client.get_zip("/api/document.xml", {"rcept_no": rcept_no})
            digest = self.store.put_zip(rcept_no, data)
            doc = parse_zip(rcept_no, data)
            self.store.put_parsed(doc, digest)
            return doc
