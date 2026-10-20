from pathlib import PurePosixPath
from typing import BinaryIO
from uuid import UUID

from app.core.config import get_settings
from app.domain.memo_upload_exceptions import InvalidMemoTitle
from app.schemas.memo import MemoSummaryResponse, MemoUploadResponse
from app.services.memo_text_extractor import MemoTextExtractor, PlainTextMemoExtractor

from app.domain.resource_exceptions import MemoNotFound, MemoVersionNotFound
from app.models import Memo, MemoVersion
from app.repositories import MemoRepository


class MemoService:
    def __init__(self, memos: MemoRepository, *, extractor: MemoTextExtractor | None = None, max_upload_bytes: int | None = None):
        self.memos = memos
        self.extractor = extractor if extractor is not None else PlainTextMemoExtractor()
        self.max_upload_bytes = max_upload_bytes

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


    def create_from_upload(self, *, stream: BinaryIO, filename: str | None, content_type: str | None, organization_id: UUID, created_by: UUID, title: str | None = None) -> MemoUploadResponse:
        limit = self.max_upload_bytes if self.max_upload_bytes is not None else get_settings().memo_upload_max_bytes
        extracted = self.extractor.extract(stream, filename=filename, content_type=content_type, max_bytes=limit)
        display_title = title.strip() if title is not None else PurePosixPath(extracted.original_filename).stem
        if not display_title or len(display_title) > 500 or "\x00" in display_title:
            raise InvalidMemoTitle()
        session = self.memos.session
        # Authentication has already autobegun this request Session. This write service
        # owns its transaction; do not open a second session.begin() or commit in Repository.
        try:
            memo = self.memos.add_memo(Memo(organization_id=organization_id, company_name=None, title=display_title, current_version=1))
            self.memos.add_version(MemoVersion(
                memo_id=memo.id, version=1, content=extracted.content, created_by=created_by,
                original_filename=extracted.original_filename, content_type=extracted.content_type,
                size_bytes=extracted.size_bytes, content_hash=extracted.content_hash,
            ))
            response = MemoUploadResponse(
                **MemoSummaryResponse.model_validate(memo).model_dump(),
                original_filename=extracted.original_filename, content_type=extracted.content_type,
                size_bytes=extracted.size_bytes, content_hash=extracted.content_hash,
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        return response
