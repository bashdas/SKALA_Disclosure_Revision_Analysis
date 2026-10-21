from uuid import UUID, uuid4

from app.domain.analysis_events import AnalysisEventType
from app.domain.analysis_exceptions import (
    AnalysisAlreadyRunning, AnalysisNotFound, AnalysisCannotBeCancelled,
    AnalysisCancelForbidden, RabbitMQPublishFailed, RabbitMQUnavailable,
)
from app.domain.exceptions import InvalidAnalysisStateTransition
from app.domain.analysis_state_machine import advance_analysis_stage, transition_analysis
from app.domain.resource_exceptions import MemoNotFound, MemoVersionNotFound
from app.infrastructure.analysis_queue import AnalysisQueueProducer
from app.models import AnalysisTask
from app.repositories import FilingRepository
from app.domain.disclosure_exceptions import DisclosureError
from app.models.enums import AnalysisStage, AnalysisStatus
from app.repositories import AnalysisEventRepository, AnalysisRepository, MemoRepository
from app.schemas.analysis import AnalysisAcceptedResponse, AnalysisDetailResponse, AnalysisCancelResponse, AnalysisEventResponse
from app.services.analysis_event import AnalysisEventService


class AnalysisService:
    def __init__(self, analyses: AnalysisRepository, memos: MemoRepository, producer: AnalysisQueueProducer):
        if analyses.session is not memos.session:
            raise ValueError("Analysis creation requires a shared Session")
        self.analyses, self.memos, self.producer = analyses, memos, producer
        self.session = analyses.session
        self.events = AnalysisEventService(analyses, AnalysisEventRepository(self.session))

    def create(self, *, memo_id: UUID, disclosure_receipt_no: str, organization_id: UUID, requested_by: UUID, memo_version: int | None = None) -> AnalysisAcceptedResponse:
        try:
            # READ COMMITTED: serialize creation for this memo, including when no active task exists.
            # Refresh the row after waiting; future version writers must lock this same row.
            memo = self.memos.get_by_id_and_organization(memo_id, organization_id, for_update=True)
            if memo is None or memo.is_deleted:
                raise MemoNotFound()
            version = memo.current_version if memo_version is None else memo_version
            if self.memos.get_version(memo.id, version, organization_id=organization_id) is None:
                raise MemoVersionNotFound()
            filing = FilingRepository(self.session).get_by_receipt_no_and_organization(disclosure_receipt_no, organization_id)
            # 분석 대상은 서버가 원문과 메타데이터를 확인한 등록 정정공시로 제한합니다.
            if filing is None or not filing.is_registered or not filing.is_correction:
                raise DisclosureError("CORRECTION_REQUIRED", "등록한 정정공시만 분석할 수 있습니다.", 422)
            duplicate = self.analyses.find_active_duplicate(organization_id, memo.id, version, disclosure_receipt_no)
            if duplicate is not None:
                raise AnalysisAlreadyRunning(duplicate.id)
            task = AnalysisTask(
                organization_id=organization_id, requested_by=requested_by,
                memo_id=memo.id, base_memo_version=version,
                disclosure_receipt_no=disclosure_receipt_no, thread_id=str(uuid4()),
                status=AnalysisStatus.CREATED, has_warnings=False,
                filing_id=filing.id, corp_code=filing.corp_code, company_name_snapshot=filing.company_name,
            )
            advance_analysis_stage(task, AnalysisStage.REQUEST_VALIDATION)
            transition_analysis(task, AnalysisStatus.QUEUED)
            self.analyses.add(task)
            self.events.append_in_transaction(task.id, organization_id, AnalysisEventType.ANALYSIS_QUEUED,
                {"status": AnalysisStatus.QUEUED, "stage": AnalysisStage.REQUEST_VALIDATION})
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
                self.session.flush()
                self.events.append_in_transaction(task.id, organization_id, AnalysisEventType.ANALYSIS_FAILED,
                    {"status": AnalysisStatus.FAILED, "code": "RABBITMQ_PUBLISH_FAILED"})
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise


    def get_analysis(self, task_id: UUID, organization_id: UUID) -> AnalysisDetailResponse:
        task = self.analyses.get_by_id_and_organization(task_id, organization_id)
        if task is None:
            raise AnalysisNotFound()
        return AnalysisDetailResponse.model_validate(task)

    def list_events(self, task_id: UUID, organization_id: UUID, *, after_sequence: int = 0, limit: int = 200) -> list[AnalysisEventResponse]:
        self.get_analysis(task_id, organization_id)
        rows = self.events.events.list_after_sequence(task_id, after_sequence, limit=limit)
        return [AnalysisEventResponse.model_validate(row) for row in rows]

    def cancel_analysis(self, task_id: UUID, organization_id: UUID, requested_by: UUID) -> AnalysisCancelResponse:
        try:
            task = self.analyses.get_by_id_and_organization(task_id, organization_id, for_update=True)
            if task is None:
                raise AnalysisNotFound()
            if task.requested_by != requested_by:
                raise AnalysisCancelForbidden()
            # Idempotency applies only after organization and requester checks.
            if task.status != AnalysisStatus.CANCELLED:
                try:
                    transition_analysis(task, AnalysisStatus.CANCELLED)
                except InvalidAnalysisStateTransition:
                    raise AnalysisCannotBeCancelled() from None
                self.session.flush()
                self.events.append_in_transaction(task.id, organization_id, AnalysisEventType.ANALYSIS_CANCELLED,
                    {"status": AnalysisStatus.CANCELLED})
            self.session.commit()
            return AnalysisCancelResponse(task_id=task_id)
        except Exception:
            self.session.rollback()
            raise
