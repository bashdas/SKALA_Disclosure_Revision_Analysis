"""Register Business Core models with the existing SQLAlchemy metadata."""
from app.models.domain import (
    AnalysisEvent, AnalysisPerspectiveTask, AnalysisReport, AnalysisTask, AuditLog,
    Contract, CompanyFavorite, Filing, FilingVersion, Memo, MemoVersion, Organization,
    RevisionProposal, User,
)

__all__ = [
    "AnalysisEvent", "AnalysisPerspectiveTask", "AnalysisReport", "AnalysisTask", "AuditLog",
    "Contract", "CompanyFavorite", "Filing", "FilingVersion", "Memo", "MemoVersion", "Organization",
    "RevisionProposal", "User",
]

from app.models.internal_report import InternalReport, InternalReportVersion, AnalysisReportReference
__all__ += ["InternalReport", "InternalReportVersion", "AnalysisReportReference"]
