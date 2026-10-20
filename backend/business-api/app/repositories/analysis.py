from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.analysis_state_machine import ACTIVE_ANALYSIS_STATUSES
from app.models import AnalysisTask


class AnalysisRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, task: AnalysisTask) -> AnalysisTask:
        self.session.add(task)
        self.session.flush()
        return task

    def get_by_id(self, task_id: UUID, *, for_update: bool = False) -> AnalysisTask | None:
        query = select(AnalysisTask).where(AnalysisTask.id == task_id)
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(query)

    def get_by_id_and_organization(self, task_id: UUID, organization_id: UUID, *, for_update: bool = False) -> AnalysisTask | None:
        query = select(AnalysisTask).where(AnalysisTask.id == task_id, AnalysisTask.organization_id == organization_id)
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(query)

    def get_by_thread_id(self, thread_id: str) -> AnalysisTask | None:
        return self.session.scalar(select(AnalysisTask).where(AnalysisTask.thread_id == thread_id))

    def list_by_organization(self, organization_id: UUID) -> list[AnalysisTask]:
        return list(self.session.scalars(select(AnalysisTask).where(AnalysisTask.organization_id == organization_id).order_by(AnalysisTask.created_at, AnalysisTask.id)))

    def find_active_duplicate(self, organization_id: UUID, memo_id: UUID, base_memo_version: int, disclosure_receipt_no: str) -> AnalysisTask | None:
        """Read only: finding no row does not lock a missing key or prevent racing inserts."""
        query = select(AnalysisTask).where(
            AnalysisTask.organization_id == organization_id,
            AnalysisTask.memo_id == memo_id,
            AnalysisTask.base_memo_version == base_memo_version,
            AnalysisTask.disclosure_receipt_no == disclosure_receipt_no,
            AnalysisTask.status.in_(ACTIVE_ANALYSIS_STATUSES),
        ).order_by(AnalysisTask.created_at, AnalysisTask.id).limit(1)
        return self.session.scalar(query)
