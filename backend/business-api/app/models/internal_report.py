"""Company-owned reference reports, independent of user memos."""
from datetime import date
from uuid import UUID

from sqlalchemy import Boolean, Date, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, false
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.common import IdentityCreatedMixin, UpdatedMixin


class InternalReport(IdentityCreatedMixin, UpdatedMixin, Base):
    __tablename__ = "internal_reports"
    __table_args__ = {"schema": "core"}
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("core.organizations.id", ondelete="RESTRICT"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    corp_code: Mapped[str] = mapped_column(String(8), index=True)
    company_name: Mapped[str] = mapped_column(String(255))
    published_at: Mapped[date] = mapped_column(Date)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class InternalReportVersion(IdentityCreatedMixin, Base):
    __tablename__ = "internal_report_versions"
    __table_args__ = (UniqueConstraint("report_id", "version", name="uq_internal_report_version"), {"schema": "core"})
    report_id: Mapped[UUID] = mapped_column(ForeignKey("core.internal_reports.id", ondelete="RESTRICT"))
    version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(500))
    corp_code: Mapped[str] = mapped_column(String(8))
    company_name: Mapped[str] = mapped_column(String(255))
    published_at: Mapped[date] = mapped_column(Date)
    original_filename: Mapped[str] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    pages: Mapped[list] = mapped_column(JSONB)
    pdf_data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("core.users.id", ondelete="RESTRICT"))


class AnalysisReportReference(Base):
    __tablename__ = "analysis_report_references"
    __table_args__ = {"schema": "core"}
    task_id: Mapped[UUID] = mapped_column(ForeignKey("core.analysis_tasks.id", ondelete="RESTRICT"), primary_key=True)
    # A manifest row also represents an intentionally empty result.
    versions: Mapped[list] = mapped_column(JSONB)
