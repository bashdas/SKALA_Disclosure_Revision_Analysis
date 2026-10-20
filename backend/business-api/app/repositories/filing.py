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
        """Receipts are unique per organization, so an unscoped lookup returns a list."""
        return list(self.session.scalars(select(Filing).where(Filing.receipt_no == receipt_no).order_by(Filing.organization_id, Filing.id)))

    def get_by_receipt_no_and_organization(self, receipt_no: str, organization_id: UUID) -> Filing | None:
        return self.session.scalar(select(Filing).where(Filing.receipt_no == receipt_no, Filing.organization_id == organization_id))

    def get_by_id_and_organization(self, filing_id: UUID, organization_id: UUID) -> Filing | None:
        return self.session.scalar(select(Filing).where(Filing.id == filing_id, Filing.organization_id == organization_id))

    def get_latest_version(self, filing_id: UUID, *, organization_id: UUID | None = None) -> FilingVersion | None:
        query = select(FilingVersion).where(FilingVersion.filing_id == filing_id)
        if organization_id is not None:
            query = query.join(Filing).where(Filing.organization_id == organization_id)
        return self.session.scalar(query.order_by(FilingVersion.version.desc()).limit(1))
