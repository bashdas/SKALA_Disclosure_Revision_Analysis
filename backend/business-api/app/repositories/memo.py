from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Memo, MemoVersion


class MemoRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_id(self, memo_id: UUID, *, for_update: bool = False) -> Memo | None:
        query = select(Memo).where(Memo.id == memo_id)
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(query)

    def get_by_id_and_organization(self, memo_id: UUID, organization_id: UUID, *, for_update: bool = False) -> Memo | None:
        query = select(Memo).where(Memo.id == memo_id, Memo.organization_id == organization_id)
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(query)

    def get_current_version(self, memo_id: UUID, *, organization_id: UUID | None = None, for_update: bool = False) -> int | None:
        query = select(Memo.current_version).where(Memo.id == memo_id)
        if organization_id is not None:
            query = query.where(Memo.organization_id == organization_id)
        if for_update:
            query = query.with_for_update()
        return self.session.scalar(query)

    def get_version(self, memo_id: UUID, version: int, *, organization_id: UUID | None = None) -> MemoVersion | None:
        query = select(MemoVersion).where(MemoVersion.memo_id == memo_id, MemoVersion.version == version)
        if organization_id is not None:
            query = query.join(Memo).where(Memo.organization_id == organization_id)
        return self.session.scalar(query)

    def list_versions(self, memo_id: UUID, *, organization_id: UUID | None = None, limit: int | None = None, offset: int = 0) -> list[MemoVersion]:
        query = select(MemoVersion).where(MemoVersion.memo_id == memo_id)
        if organization_id is not None:
            query = query.join(Memo).where(Memo.organization_id == organization_id)
        return list(self.session.scalars(query.order_by(MemoVersion.version).limit(limit).offset(offset)))


    def list_by_organization(self, organization_id: UUID, *, limit: int = 20, offset: int = 0, company_name: str | None = None) -> list[Memo]:
        query = select(Memo).where(Memo.organization_id == organization_id, Memo.is_deleted.is_(False))
        if company_name is not None:
            query = query.where(Memo.company_name == company_name)
        return list(self.session.scalars(query.order_by(Memo.updated_at.desc(), Memo.id.desc()).limit(limit).offset(offset)))


    def add_memo(self, memo: Memo) -> Memo:
        self.session.add(memo)
        self.session.flush()
        return memo

    def add_version(self, version: MemoVersion) -> MemoVersion:
        self.session.add(version)
        self.session.flush()
        return version
