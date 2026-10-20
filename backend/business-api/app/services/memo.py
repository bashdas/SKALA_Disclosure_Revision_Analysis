from uuid import UUID

from app.domain.resource_exceptions import MemoNotFound, MemoVersionNotFound
from app.models import Memo, MemoVersion
from app.repositories import MemoRepository


class MemoService:
    def __init__(self, memos: MemoRepository):
        self.memos = memos

    def list_memos(self, organization_id: UUID, *, limit: int = 20, offset: int = 0, company_name: str | None = None) -> list[Memo]:
        return self.memos.list_by_organization(organization_id, limit=limit, offset=offset, company_name=company_name)

    def get_memo(self, memo_id: UUID, organization_id: UUID) -> Memo:
        memo = self.memos.get_by_id_and_organization(memo_id, organization_id)
        if memo is None:
            raise MemoNotFound()
        return memo

    def list_versions(self, memo_id: UUID, organization_id: UUID, *, limit: int = 20, offset: int = 0) -> list[MemoVersion]:
        self.get_memo(memo_id, organization_id)
        return self.memos.list_versions(memo_id, organization_id=organization_id, limit=limit, offset=offset)

    def get_version(self, memo_id: UUID, version: int, organization_id: UUID) -> MemoVersion:
        self.get_memo(memo_id, organization_id)
        result = self.memos.get_version(memo_id, version, organization_id=organization_id)
        if result is None:
            raise MemoVersionNotFound()
        return result

    def get_current_version(self, memo_id: UUID, organization_id: UUID) -> MemoVersion:
        memo = self.get_memo(memo_id, organization_id)
        result = self.memos.get_version(memo_id, memo.current_version, organization_id=organization_id)
        if result is None:
            raise MemoVersionNotFound()
        return result
