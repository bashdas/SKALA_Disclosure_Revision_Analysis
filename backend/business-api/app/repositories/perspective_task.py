from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.perspective_state_machine import ACTIVE_PERSPECTIVE_STATUSES
from app.models import AnalysisPerspectiveTask
from app.models.enums import PerspectiveType


class PerspectiveTaskRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, task: AnalysisPerspectiveTask) -> AnalysisPerspectiveTask:
        self.session.add(task)
        self.session.flush()
        return task

    def get_by_id(self, task_id: UUID) -> AnalysisPerspectiveTask | None:
        return self.session.get(AnalysisPerspectiveTask, task_id)

    def get_by_analysis_task_and_type(self, analysis_task_id: UUID, perspective_type: PerspectiveType) -> AnalysisPerspectiveTask | None:
        return self.session.scalar(select(AnalysisPerspectiveTask).where(AnalysisPerspectiveTask.analysis_task_id == analysis_task_id, AnalysisPerspectiveTask.perspective_type == perspective_type))

    def list_by_analysis_task(self, analysis_task_id: UUID) -> list[AnalysisPerspectiveTask]:
        return list(self.session.scalars(select(AnalysisPerspectiveTask).where(AnalysisPerspectiveTask.analysis_task_id == analysis_task_id).order_by(AnalysisPerspectiveTask.created_at, AnalysisPerspectiveTask.id)))

    def list_active_by_analysis_task(self, analysis_task_id: UUID) -> list[AnalysisPerspectiveTask]:
        return list(self.session.scalars(select(AnalysisPerspectiveTask).where(AnalysisPerspectiveTask.analysis_task_id == analysis_task_id, AnalysisPerspectiveTask.status.in_(ACTIVE_PERSPECTIVE_STATUSES)).order_by(AnalysisPerspectiveTask.created_at, AnalysisPerspectiveTask.id)))

    def get_by_id_and_analysis_task(self, perspective_id: UUID, analysis_task_id: UUID) -> AnalysisPerspectiveTask | None:
        query = select(AnalysisPerspectiveTask).where(
            AnalysisPerspectiveTask.id == perspective_id,
            AnalysisPerspectiveTask.analysis_task_id == analysis_task_id,
        ).execution_options(populate_existing=True)
        return self.session.scalar(query)
