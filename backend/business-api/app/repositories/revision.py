from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RevisionProposal


class RevisionRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, proposal: RevisionProposal) -> RevisionProposal:
        self.session.add(proposal)
        self.session.flush()
        return proposal

    def get_by_id(self, proposal_id: UUID) -> RevisionProposal | None:
        return self.session.get(RevisionProposal, proposal_id)

    def list_by_analysis_task(self, analysis_task_id: UUID) -> list[RevisionProposal]:
        return list(self.session.scalars(select(RevisionProposal).where(RevisionProposal.analysis_task_id == analysis_task_id).order_by(RevisionProposal.created_at, RevisionProposal.id)))
