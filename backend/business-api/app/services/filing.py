from uuid import UUID

from app.domain.resource_exceptions import FilingNotFound, FilingVersionNotFound
from app.models import Filing, FilingVersion
from app.repositories import FilingRepository


class FilingService:
    """Read stored cache/snapshots only; no external calls or cache requirement for analyses."""
    def __init__(self, filings: FilingRepository):
        self.filings = filings

    def list_filings(self, organization_id: UUID, *, limit: int = 20, offset: int = 0, company_name: str | None = None, filing_type: str | None = None) -> list[Filing]:
        return self.filings.list_by_organization(organization_id, limit=limit, offset=offset, company_name=company_name, filing_type=filing_type)

    def get_filing(self, filing_id: UUID, organization_id: UUID) -> Filing:
        filing = self.filings.get_by_id_and_organization(filing_id, organization_id)
        if filing is None:
            raise FilingNotFound()
        return filing

    def get_by_receipt_no_and_organization(self, receipt_no: str, organization_id: UUID) -> Filing:
        filing = self.filings.get_by_receipt_no_and_organization(receipt_no, organization_id)
        if filing is None:
            raise FilingNotFound()
        return filing

    def list_versions(self, filing_id: UUID, organization_id: UUID, *, limit: int = 20, offset: int = 0) -> list[FilingVersion]:
        self.get_filing(filing_id, organization_id)
        return self.filings.list_versions(filing_id, organization_id=organization_id, limit=limit, offset=offset)

    def get_version(self, filing_id: UUID, version: int, organization_id: UUID) -> FilingVersion:
        self.get_filing(filing_id, organization_id)
        result = self.filings.get_version(filing_id, version, organization_id=organization_id)
        if result is None:
            raise FilingVersionNotFound()
        return result
