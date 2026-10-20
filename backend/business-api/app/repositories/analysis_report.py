from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnalysisReport


class AnalysisReportRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, report: AnalysisReport) -> AnalysisReport:
        self.session.add(report)
        self.session.flush()
        return report

    def get_by_id(self, report_id: UUID) -> AnalysisReport | None:
        return self.session.get(AnalysisReport, report_id)

    def get_by_analysis_task(self, analysis_task_id: UUID) -> AnalysisReport | None:
        return self.session.scalar(select(AnalysisReport).where(AnalysisReport.analysis_task_id == analysis_task_id))

    def exists_by_analysis_task(self, analysis_task_id: UUID) -> bool:
        return bool(self.session.scalar(select(select(AnalysisReport.id).where(AnalysisReport.analysis_task_id == analysis_task_id).exists())))
