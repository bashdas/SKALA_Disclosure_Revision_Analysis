from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Filing, FilingVersion


class FilingRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_id(self, filing_id: UUID) -> Filing | None:
        return self.session.get(Filing, filing_id)

    def list_by_receipt_no(self, receipt_no: str) -> list[Filing]:
        """Return matching receipts for compatibility with existing callers."""
        return list(self.session.scalars(select(Filing).where(Filing.receipt_no == receipt_no).order_by(Filing.id)))

    def get_by_receipt_no(self, receipt_no: str) -> Filing | None:
        return self.session.scalar(select(Filing).where(Filing.receipt_no == receipt_no))


    def get_latest_version(self, filing_id: UUID) -> FilingVersion | None:
        query = select(FilingVersion).where(FilingVersion.filing_id == filing_id)
        return self.session.scalar(query.order_by(FilingVersion.version.desc()).limit(1))


    def list_all(self, *, limit: int = 20, offset: int = 0, company_name: str | None = None, filing_type: str | None = None) -> list[Filing]:
        query = select(Filing).where(Filing.is_registered.is_(True))
        if company_name is not None:
            query = query.where(Filing.company_name == company_name)
        if filing_type is not None:
            query = query.where(Filing.filing_type == filing_type)
        return list(self.session.scalars(query.order_by(Filing.filed_at.desc(), Filing.id.desc()).limit(limit).offset(offset)))

    def list_versions(self, filing_id: UUID, *, limit: int | None = None, offset: int = 0) -> list[FilingVersion]:
        query = select(FilingVersion).where(FilingVersion.filing_id == filing_id)
        return list(self.session.scalars(query.order_by(FilingVersion.version).limit(limit).offset(offset)))

    def get_version(self, filing_id: UUID, version: int) -> FilingVersion | None:
        query = select(FilingVersion).where(FilingVersion.filing_id == filing_id, FilingVersion.version == version)
        return self.session.scalar(query)
