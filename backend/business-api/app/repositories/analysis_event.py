from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sqlalchemy import func

from app.models import AnalysisEvent


class AnalysisEventRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, event: AnalysisEvent) -> AnalysisEvent:
        self.session.add(event)
        self.session.flush()
        return event

    def list_by_analysis_task(self, analysis_task_id: UUID) -> list[AnalysisEvent]:
        return list(self.session.scalars(select(AnalysisEvent).where(AnalysisEvent.analysis_task_id == analysis_task_id).order_by(AnalysisEvent.sequence)))

    def get_latest_sequence(self, analysis_task_id: UUID) -> int:
        """Zero means no events. This query never reserves or allocates a sequence."""
        return self.session.scalar(select(func.coalesce(func.max(AnalysisEvent.sequence), 0)).where(AnalysisEvent.analysis_task_id == analysis_task_id))

    def list_after_sequence(self, analysis_task_id: UUID, after_sequence: int, *, limit: int = 200) -> list[AnalysisEvent]:
        query = select(AnalysisEvent).where(
            AnalysisEvent.analysis_task_id == analysis_task_id,
            AnalysisEvent.sequence > after_sequence,
        ).order_by(AnalysisEvent.sequence).limit(limit)
        return list(self.session.scalars(query))
