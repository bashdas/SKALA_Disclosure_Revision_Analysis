from uuid import UUID
from datetime import datetime, timezone
from hashlib import sha256
import re
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from app.domain.disclosure_exceptions import DisclosureError
from app.services.disclosure_source import DisclosureSource

from app.domain.resource_exceptions import FilingNotFound, FilingVersionNotFound
from app.models import Filing, FilingVersion
from app.repositories import FilingRepository


class FilingService:
    """등록한 공시의 조회와 OpenDART 원문 등록을 처리합니다."""
    def __init__(self, filings: FilingRepository, source: DisclosureSource | None = None):
        self.filings, self.source = filings, source

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


    def register(self, receipt_no: str, organization_id: UUID, *, origin: str | None = None, automatic: bool = False) -> Filing:
        session = self.filings.session
        existing = self.filings.get_by_receipt_no_and_organization(receipt_no, organization_id)
        if automatic and existing is not None:
            return existing
        if self.source is None:
            raise DisclosureError()
        data = self.source.call("get_disclosure", {"receipt_no": receipt_no})
        try:
            name, title, corp = data["company_name"], data["report_name"], data["corp_code"]
            content = data["document"]["text"]
            filed = datetime.fromisoformat(data["filed_at"]).replace(tzinfo=timezone.utc)
            if (data["receipt_no"] != receipt_no or data.get("metadata_status") != "FOUND"
                or not isinstance(name, str) or not 1 <= len(name) <= 255
                or not isinstance(title, str) or not 1 <= len(title) <= 500
                or (not receipt_no.startswith("SEC:") and (not isinstance(corp, str) or not re.fullmatch(r"[0-9]{8}", corp)))
                or not isinstance(content, str) or not content.strip() or "\x00" in content):
                raise ValueError()
        except (KeyError, ValueError, TypeError):
            raise DisclosureError("DISCLOSURE_METADATA_UNCONFIRMED", "공시의 회사 정보와 원문을 확인하지 못했습니다.") from None
        try:
            is_correction = bool(re.match(r"^\[(?:기재|첨부)?정정\]", title)) or (
                receipt_no.startswith("SEC:") and title.startswith("8-K/A ")
            )
            values = dict(organization_id=organization_id, receipt_no=receipt_no,
                company_name=name, corp_code=corp, title=title,
                filing_type="정정공시" if is_correction else "신규공시",
                is_correction=is_correction, is_registered=True, filed_at=filed)
            if origin:
                values["origin_receipt_no"] = origin
            # 같은 공시를 동시에 등록해도 조직별 접수번호의 고유 제약으로 한 건만 저장합니다.
            command = insert(Filing).values(**values)
            changes = {key: value for key, value in values.items() if key not in ("organization_id", "receipt_no")}
            filing = session.scalar(command.on_conflict_do_update(
                constraint="uq_filings_organization_receipt", set_=changes).returning(Filing), execution_options={"populate_existing": True})
            digest = sha256(content.encode("utf-8")).hexdigest()
            session.execute(insert(FilingVersion).values(filing_id=filing.id, version=1,
                raw_content=content, content_hash=digest).on_conflict_do_nothing(constraint="uq_filing_versions_filing_version"))
            session.commit()
            return filing
        except Exception:
            session.rollback()
            raise

    def unregister(self, filing_id: UUID, organization_id: UUID) -> None:
        session = self.filings.session
        try:
            filing = self.get_filing(filing_id, organization_id)
            # 기존 분석과 근거가 참조하는 원문은 보존하고 등록 목록에서 제외합니다.
            filing.is_registered = False
            if filing.origin_receipt_no is None:
                session.execute(update(Filing).where(Filing.organization_id == organization_id,
                    Filing.origin_receipt_no == filing.receipt_no).values(is_registered=False))
            session.commit()
        except Exception:
            session.rollback()
            raise

    def check_corrections(self, filing_id: UUID, organization_id: UUID) -> list[Filing]:
        filing = self.get_filing(filing_id, organization_id)
        if not filing.is_registered or self.source is None:
            raise FilingNotFound()
        receipt = filing.origin_receipt_no or filing.receipt_no
        family = self.source.call("opendart_get_disclosure_family", {"receipt_no": receipt})
        for row in family.get("items", []):
            correction = row.get("receipt_no", "")
            if (row.get("is_correction") is True and isinstance(correction, str)
                and re.fullmatch(r"[0-9]{14}", correction) and correction > receipt):
                self.register(correction, organization_id, origin=receipt, automatic=True)
        return list(self.filings.session.scalars(select(Filing).where(
            Filing.organization_id == organization_id, Filing.origin_receipt_no == receipt,
            Filing.is_registered.is_(True)).order_by(Filing.filed_at.desc(), Filing.id)))
