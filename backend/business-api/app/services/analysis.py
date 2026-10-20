from uuid import UUID, uuid4

from app.domain.analysis_exceptions import AnalysisAlreadyRunning, RabbitMQPublishFailed, RabbitMQUnavailable
from app.domain.analysis_state_machine import advance_analysis_stage, transition_analysis
from app.domain.resource_exceptions import MemoNotFound, MemoVersionNotFound
from app.infrastructure.analysis_queue import AnalysisQueueProducer
from app.models import AnalysisTask
from app.models.enums import AnalysisStage, AnalysisStatus
from app.repositories import AnalysisRepository, MemoRepository
from app.schemas.analysis import AnalysisAcceptedResponse


class AnalysisService:
    def __init__(self, analyses: AnalysisRepository, memos: MemoRepository, producer: AnalysisQueueProducer):
        if analyses.session is not memos.session:
            raise ValueError("Analysis creation requires a shared Session")
        self.analyses, self.memos, self.producer = analyses, memos, producer
        self.session = analyses.session

    def create(self, *, memo_id: UUID, disclosure_receipt_no: str, organization_id: UUID, requested_by: UUID) -> AnalysisAcceptedResponse:
        try:
            # READ COMMITTED: serialize creation for this memo, including when no active task exists.
            # Refresh the row after waiting; future version writers must lock this same row.
            memo = self.memos.get_by_id_and_organization(memo_id, organization_id, for_update=True)
            if memo is None:
                raise MemoNotFound()
            version = memo.current_version
            if self.memos.get_version(memo.id, version, organization_id=organization_id) is None:
                raise MemoVersionNotFound()
            duplicate = self.analyses.find_active_duplicate(organization_id, memo.id, version, disclosure_receipt_no)
            if duplicate is not None:
                raise AnalysisAlreadyRunning(duplicate.id)
            task = AnalysisTask(
                organization_id=organization_id, requested_by=requested_by,
                memo_id=memo.id, base_memo_version=version,
                disclosure_receipt_no=disclosure_receipt_no, thread_id=str(uuid4()),
                status=AnalysisStatus.CREATED, has_warnings=False,
                corp_code=None, company_name_snapshot=None,
            )
            advance_analysis_stage(task, AnalysisStage.REQUEST_VALIDATION)
            transition_analysis(task, AnalysisStatus.QUEUED)
            self.analyses.add(task)
            response = AnalysisAcceptedResponse(task_id=task.id, created_at=task.created_at)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        try:
            self.producer.publish_analysis(response.task_id)
        except (RabbitMQPublishFailed, RabbitMQUnavailable):
            self._record_publish_failure(response.task_id, organization_id)
            raise RabbitMQPublishFailed() from None
        return response

    def _record_publish_failure(self, task_id: UUID, organization_id: UUID) -> None:
        try:
            task = self.analyses.get_by_id_and_organization(task_id, organization_id, for_update=True)
            # A lost confirmation can mean a worker already received the message. Do not
            # overwrite worker progress/terminal results after an ambiguous delivery.
            if task is not None and task.status == AnalysisStatus.QUEUED:
                transition_analysis(task, AnalysisStatus.FAILED)
                task.error_stage = AnalysisStage.REQUEST_VALIDATION
                task.error_code = "RABBITMQ_PUBLISH_FAILED"
                task.error_message = "Queue publish failed after bounded attempts"
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
