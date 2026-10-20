"""Register all Business Core models with the existing SQLAlchemy metadata."""
from app.models.domain import (
    AnalysisEvent, AnalysisTask, Approval, ApprovalItem, AuditLog, Contract,
    Filing, FilingVersion, Memo, MemoVersion, Organization, RevisionApplication,
    RevisionProposal, User,
)

__all__ = [
    "AnalysisEvent", "AnalysisTask", "Approval", "ApprovalItem", "AuditLog", "Contract",
    "Filing", "FilingVersion", "Memo", "MemoVersion", "Organization", "RevisionApplication",
    "RevisionProposal", "User",
]
