from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4
from typing import Any

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index,
    Integer, Numeric, String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import CORE_SCHEMA, IdentityCreatedMixin, UpdatedMixin
from app.models.enums import (
    AnalysisStatus, ApprovalStatus, ImpactType, UserRole, ValidationStatus, enum_column,
)

class Organization(IdentityCreatedMixin, Base):
    __tablename__ = "organizations"
    __table_args__ = {"schema": CORE_SCHEMA}

    name: Mapped[str] = mapped_column(String(255))
    users: Mapped[list[User]] = relationship(passive_deletes="all")
    filings: Mapped[list[Filing]] = relationship(passive_deletes="all")
    memos: Mapped[list[Memo]] = relationship(passive_deletes="all")
    analysis_tasks: Mapped[list[AnalysisTask]] = relationship(passive_deletes="all")


class User(IdentityCreatedMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        Index("ix_users_organization_id", "organization_id"),
        {"schema": CORE_SCHEMA},
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("core.organizations.id", ondelete="RESTRICT"))
    email: Mapped[str] = mapped_column(String(320))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(enum_column(UserRole, "ck_users_role"))


class Filing(IdentityCreatedMixin, Base):
    __tablename__ = "filings"
    __table_args__ = (
        UniqueConstraint("organization_id", "receipt_no", name="uq_filings_organization_receipt"),
        Index("ix_filings_receipt_no", "receipt_no"),
        {"schema": CORE_SCHEMA},
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("core.organizations.id", ondelete="RESTRICT"))
    company_name: Mapped[str] = mapped_column(String(255))
    receipt_no: Mapped[str] = mapped_column(String(64))
    filing_type: Mapped[str] = mapped_column(String(100))
    filed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FilingVersion(IdentityCreatedMixin, Base):
    __tablename__ = "filing_versions"
    __table_args__ = (
        UniqueConstraint("filing_id", "version", name="uq_filing_versions_filing_version"),
        CheckConstraint("version >= 1", name="ck_filing_versions_version_positive"),
        {"schema": CORE_SCHEMA},
    )

    filing_id: Mapped[UUID] = mapped_column(ForeignKey("core.filings.id", ondelete="RESTRICT"))
    version: Mapped[int] = mapped_column(Integer)
    raw_content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(128))


class Contract(IdentityCreatedMixin, Base):
    __tablename__ = "contracts"
    __table_args__ = {"schema": CORE_SCHEMA}

    filing_id: Mapped[UUID] = mapped_column(ForeignKey("core.filings.id", ondelete="RESTRICT"), index=True)
    contract_name: Mapped[str] = mapped_column(String(255))
    counterparty: Mapped[str | None] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 4))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)


class Memo(IdentityCreatedMixin, UpdatedMixin, Base):
    __tablename__ = "memos"
    __table_args__ = (
        CheckConstraint("current_version >= 1", name="ck_memos_current_version_positive"),
        {"schema": CORE_SCHEMA},
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("core.organizations.id", ondelete="RESTRICT"), index=True)
    company_name: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(500))
    current_version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    memo_versions: Mapped[list[MemoVersion]] = relationship(passive_deletes="all", order_by="MemoVersion.version")


class MemoVersion(IdentityCreatedMixin, Base):
    __tablename__ = "memo_versions"
    __table_args__ = (
        UniqueConstraint("memo_id", "version", name="uq_memo_versions_memo_version"),
        CheckConstraint("version >= 1", name="ck_memo_versions_version_positive"),
        {"schema": CORE_SCHEMA},
    )

    memo_id: Mapped[UUID] = mapped_column(ForeignKey("core.memos.id", ondelete="RESTRICT"))
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("core.users.id", ondelete="RESTRICT"))


class AnalysisTask(IdentityCreatedMixin, UpdatedMixin, Base):
    __tablename__ = "analysis_tasks"
    __table_args__ = (
        CheckConstraint("base_memo_version >= 1", name="ck_analysis_tasks_base_version_positive"),
        UniqueConstraint("thread_id", name="uq_analysis_tasks_thread_id"),
        Index("ix_analysis_tasks_organization_status", "organization_id", "status"),
        Index("ix_analysis_tasks_status", "status"),
        {"schema": CORE_SCHEMA},
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("core.organizations.id", ondelete="RESTRICT"))
    requested_by: Mapped[UUID] = mapped_column(ForeignKey("core.users.id", ondelete="RESTRICT"))
    filing_id: Mapped[UUID] = mapped_column(ForeignKey("core.filings.id", ondelete="RESTRICT"), index=True)
    memo_id: Mapped[UUID] = mapped_column(ForeignKey("core.memos.id", ondelete="RESTRICT"), index=True)
    base_memo_version: Mapped[int] = mapped_column(Integer)
    thread_id: Mapped[str] = mapped_column(String(255))
    status: Mapped[AnalysisStatus] = mapped_column(
        enum_column(AnalysisStatus, "ck_analysis_tasks_status"),
        default=AnalysisStatus.CREATED, server_default=AnalysisStatus.CREATED.value,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    revision_proposals: Mapped[list[RevisionProposal]] = relationship(passive_deletes="all")
    analysis_events: Mapped[list[AnalysisEvent]] = relationship(passive_deletes="all", order_by="AnalysisEvent.sequence")
    approval: Mapped[Approval | None] = relationship(passive_deletes="all", uselist=False)


class RevisionProposal(IdentityCreatedMixin, Base):
    __tablename__ = "revision_proposals"
    __table_args__ = {"schema": CORE_SCHEMA}

    analysis_task_id: Mapped[UUID] = mapped_column(ForeignKey("core.analysis_tasks.id", ondelete="RESTRICT"), index=True)
    claim_id: Mapped[str] = mapped_column(String(255))
    impact_type: Mapped[ImpactType] = mapped_column(enum_column(ImpactType, "ck_revision_proposals_impact_type"))
    before_text: Mapped[str] = mapped_column(Text)
    after_text: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    validation_status: Mapped[ValidationStatus] = mapped_column(
        enum_column(ValidationStatus, "ck_revision_proposals_validation_status"),
        default=ValidationStatus.PENDING, server_default=ValidationStatus.PENDING.value,
    )


class Approval(IdentityCreatedMixin, Base):
    __tablename__ = "approvals"
    __table_args__ = (
        UniqueConstraint("analysis_task_id", name="uq_approvals_analysis_task_id"),
        {"schema": CORE_SCHEMA},
    )

    analysis_task_id: Mapped[UUID] = mapped_column(ForeignKey("core.analysis_tasks.id", ondelete="RESTRICT"))
    approved_by: Mapped[UUID | None] = mapped_column(ForeignKey("core.users.id", ondelete="RESTRICT"))
    status: Mapped[ApprovalStatus] = mapped_column(
        enum_column(ApprovalStatus, "ck_approvals_status"),
        default=ApprovalStatus.PENDING, server_default=ApprovalStatus.PENDING.value,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_items: Mapped[list[ApprovalItem]] = relationship(passive_deletes="all")


class ApprovalItem(Base):
    __tablename__ = "approval_items"
    __table_args__ = (
        UniqueConstraint("approval_id", "revision_proposal_id", name="uq_approval_items_approval_proposal"),
        {"schema": CORE_SCHEMA},
    )

    # No created_at field is needed for this association in the current contract.
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    approval_id: Mapped[UUID] = mapped_column(ForeignKey("core.approvals.id", ondelete="RESTRICT"))
    revision_proposal_id: Mapped[UUID] = mapped_column(ForeignKey("core.revision_proposals.id", ondelete="RESTRICT"))
    approved: Mapped[bool] = mapped_column(Boolean)


class AnalysisEvent(IdentityCreatedMixin, Base):
    __tablename__ = "analysis_events"
    __table_args__ = (
        UniqueConstraint("analysis_task_id", "sequence", name="uq_analysis_events_task_sequence"),
        CheckConstraint("sequence >= 1", name="ck_analysis_events_sequence_positive"),
        {"schema": CORE_SCHEMA},
    )

    analysis_task_id: Mapped[UUID] = mapped_column(ForeignKey("core.analysis_tasks.id", ondelete="RESTRICT"))
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(100))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))


class AuditLog(IdentityCreatedMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_organization_created", "organization_id", "created_at"),
        {"schema": CORE_SCHEMA},
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("core.organizations.id", ondelete="RESTRICT"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("core.users.id", ondelete="RESTRICT"))
    action: Mapped[str] = mapped_column(String(100))
    resource_type: Mapped[str] = mapped_column(String(100))
    resource_id: Mapped[str] = mapped_column(String(255))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))


class RevisionApplication(IdentityCreatedMixin, Base):
    __tablename__ = "revision_applications"
    __table_args__ = (
        UniqueConstraint("revision_proposal_id", name="uq_revision_applications_proposal"),
        CheckConstraint("result_memo_version >= 1", name="ck_revision_applications_result_version_positive"),
        Index("ix_revision_applications_analysis_task_id", "analysis_task_id"),
        {"schema": CORE_SCHEMA},
    )

    analysis_task_id: Mapped[UUID] = mapped_column(ForeignKey("core.analysis_tasks.id", ondelete="RESTRICT"))
    approval_id: Mapped[UUID] = mapped_column(ForeignKey("core.approvals.id", ondelete="RESTRICT"))
    revision_proposal_id: Mapped[UUID] = mapped_column(ForeignKey("core.revision_proposals.id", ondelete="RESTRICT"))
    result_memo_version: Mapped[int] = mapped_column(Integer)
