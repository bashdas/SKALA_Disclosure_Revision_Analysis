"""[MOCK] OpenDART·PostgreSQL 없이 Tool을 실행하기 위한 테스트 더블.

- MockDartCore: dart_core.interface.DartCore 구현. data/companies.json, filings.json, documents/*.json 사용
- MockMemoRepository: services.memos.MemoRepository 구현. data/memos.json 사용

데이터는 모두 가상값이며, 응답 meta.source="mock"과 MOCK_DATA 경고로 표시됩니다.
실데이터로 바꿀 때는 이 모듈을 고치지 말고 business_mcp/providers.py에서 구현체를 교체하세요.
"""

import json
from datetime import date
from pathlib import Path
from typing import Literal

from business_mcp.schemas import AnalysisMemo
from dart_core.corp_codes import resolve
from dart_core.models import CompanyHit, FilingMeta, ParsedDocument
from dart_core.status import DartNotFound
from dart_core.titles import to_filing_meta

DATA_DIR = Path(__file__).parent / "data"


def _load(path: Path) -> list | dict:
    return json.loads(path.read_text(encoding="utf-8"))["items"]


class MockDartCore:
    source = "mock"

    def __init__(self, companies: list[dict], filings: list[dict], documents: dict[str, dict]):
        self.companies = companies
        self.filings = [to_filing_meta(row) for row in filings]
        self.documents = documents
        self.calls: list[str] = []  # 테스트에서 호출 여부 확인용

    @classmethod
    def from_dir(cls, data_dir: Path = DATA_DIR) -> "MockDartCore":
        docs = {p.stem: _load(p) for p in sorted((data_dir / "documents").glob("*.json"))}
        return cls(_load(data_dir / "companies.json"), _load(data_dir / "filings.json"), docs)

    async def resolve_company(self, query: str) -> tuple[CompanyHit | None, list[CompanyHit]]:
        self.calls.append("resolve_company")
        return resolve(self.companies, query)  # live(CorpCodeIndex)와 같은 해석 규칙

    async def list_filings(
        self, corp_code: str, date_from: date, date_to: date, *, last_reprt_at: Literal["Y", "N"] = "N",
        pblntf_ty: str | None = None, max_pages: int = 3,
    ) -> tuple[list[FilingMeta], int]:
        self.calls.append("list_filings")
        rows = [
            f for f in self.filings
            if f.corp_code == corp_code and date_from <= f.rcept_dt <= date_to
            and (pblntf_ty is None or f.pblntf_ty == pblntf_ty)
            and (last_reprt_at == "N" or not f.has_later_correction)
        ]
        rows.sort(key=lambda f: f.rcept_no, reverse=True)  # OpenDART 기본 정렬: 접수일 내림차순
        return rows[: max_pages * 100], len(rows)

    async def find_filing(self, rcept_no: str, corp_code: str | None = None) -> FilingMeta | None:
        self.calls.append("find_filing")
        return next((f for f in self.filings if f.rcept_no == rcept_no), None)

    async def ingest_filing(self, rcept_no: str) -> ParsedDocument:
        self.calls.append("ingest_filing")
        if rcept_no not in self.documents:
            raise DartNotFound("014", f"[MOCK] 접수번호 {rcept_no}의 원문 fixture가 없습니다.")
        return ParsedDocument.model_validate(self.documents[rcept_no])


class MockMemoRepository:
    source = "mock"

    def __init__(self, memos: list[dict]):
        self.memos = {m["memo_id"]: m for m in memos}

    @classmethod
    def from_dir(cls, data_dir: Path = DATA_DIR) -> "MockMemoRepository":
        return cls(_load(data_dir / "memos.json"))

    @staticmethod
    def _to_model(m: dict, v: dict) -> AnalysisMemo:
        return AnalysisMemo(
            memo_id=m["memo_id"], corp_code=m["corp_code"], corp_name=m.get("corp_name"), title=m["title"],
            author=m["author"], version=v["version"], updated_at=v["created_at"],
            source_rcept_nos=v["source_rcept_nos"], sections=v["sections"],
        )

    async def get_memo(self, memo_id: str, version: int | None = None) -> AnalysisMemo | None:
        m = self.memos.get(memo_id)
        if m is None:
            return None
        versions = {v["version"]: v for v in m["versions"]}
        v = versions.get(version if version is not None else max(versions))
        return self._to_model(m, v) if v else None

    async def list_memos(self, corp_code: str) -> list[AnalysisMemo]:
        latest = [self._to_model(m, max(m["versions"], key=lambda v: v["version"]))
                  for m in self.memos.values() if m["corp_code"] == corp_code]
        return sorted(latest, key=lambda m: m.updated_at, reverse=True)
