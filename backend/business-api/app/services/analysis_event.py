from uuid import UUID

from pydantic import ValidationError

from app.domain.analysis_events import AnalysisEventType
from app.domain.analysis_exceptions import AnalysisNotFound, InvalidEventPayload
from app.models import AnalysisEvent
from app.repositories import AnalysisEventRepository, AnalysisRepository
from app.schemas.analysis import AnalysisEventPayload, AnalysisEventResponse


class AnalysisEventService:
    def __init__(self, analyses: AnalysisRepository, events: AnalysisEventRepository):
        if analyses.session is not events.session:
            raise ValueError("Event append requires a shared Session")
        self.analyses, self.events = analyses, events
        self.session = analyses.session

    def append_in_transaction(self, task_id: UUID, organization_id: UUID, event_type: AnalysisEventType, payload: dict) -> AnalysisEventResponse:
        """Compose with caller's transaction. Caller flushes pending Task edits first.

        The parent row lock is held until caller commits/rolls back. Every writer must
        use this protocol; the existing unique constraint remains the final safeguard.
        """
        try:
            event_type = AnalysisEventType(event_type)
            summary = AnalysisEventPayload.model_validate(payload).model_dump(mode="json", exclude_none=True)
        except (ValueError, ValidationError):
            raise InvalidEventPayload() from None
        if self.analyses.get_by_id_and_organization(task_id, organization_id, for_update=True) is None:
            raise AnalysisNotFound()
        sequence = self.events.get_latest_sequence(task_id) + 1
        row = self.events.add(AnalysisEvent(analysis_task_id=task_id, sequence=sequence,
            event_type=event_type.value, payload_json=summary))
        return AnalysisEventResponse.model_validate(row)

    def append_event(self, task_id: UUID, organization_id: UUID, event_type: AnalysisEventType, payload: dict) -> AnalysisEventResponse:
        """Standalone append owns commit/rollback; never call during another workflow."""
        try:
            result = self.append_in_transaction(task_id, organization_id, event_type, payload)
            self.session.commit()
            return result
        except Exception:
            self.session.rollback()
            raise
