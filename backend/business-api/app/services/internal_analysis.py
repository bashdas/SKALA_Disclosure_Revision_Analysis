from contextlib import contextmanager
from time import sleep
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.domain.analysis_events import AnalysisEventType as E
from app.domain.analysis_exceptions import AnalysisNotFound
from app.domain.analysis_state_machine import TERMINAL_ANALYSIS_STATUSES, advance_analysis_stage, transition_analysis
from app.domain.clock import utc_timestamp
from app.domain.exceptions import InvalidAnalysisStageTransition, InvalidAnalysisStateTransition, InvalidPerspectiveStateTransition
from app.domain.internal_exceptions import InternalAPIError
from app.domain.perspective_state_machine import transition_perspective
from app.domain.resource_exceptions import MemoVersionNotFound
from app.models import AnalysisPerspectiveTask, AnalysisReport
from app.models.enums import AnalysisStatus as S, AnalysisStage as G, PerspectiveStatus as P
from app.repositories import FilingRepository, AnalysisEventRepository, AnalysisRepository, AnalysisReportRepository, MemoRepository, PerspectiveTaskRepository
from app.schemas.analysis import AnalysisEventResponse
from app.schemas.internal import (
    AnalysisContextResponse, ContextMemo, InternalEventRequest, InternalStateRequest,
    InternalStatusResponse, PerspectiveCreateRequest, PerspectiveUpdateRequest,
    PerspectiveResponse, ReportSaveRequest, ReportSavedResponse,
)
from app.services.analysis_event import AnalysisEventService

SERVER_EVENTS = frozenset({E.ANALYSIS_QUEUED, E.ANALYSIS_STARTED, E.ANALYSIS_FAILED,
    E.ANALYSIS_CANCELLED, E.ANALYSIS_COMPLETED, E.PERSPECTIVE_SELECTED,
    E.PERSPECTIVE_STARTED, E.PERSPECTIVE_COMPLETED, E.PERSPECTIVE_FAILED,
    E.REPORT_SAVE_STARTED, E.REPORT_SAVE_FAILED, E.REPORT_SAVED})
STATUS_EVENTS = {S.RUNNING: E.ANALYSIS_STARTED, S.SAVING: E.REPORT_SAVE_STARTED,
    S.SAVE_FAILED: E.REPORT_SAVE_FAILED, S.FAILED: E.ANALYSIS_FAILED, S.CANCELLED: E.ANALYSIS_CANCELLED}


class InternalAnalysisService:
    def __init__(self, session: Session, settings: Settings, *, sleeper=sleep):
        self.session, self.settings, self.sleep = session, settings, sleeper
        self.analyses = AnalysisRepository(session)
        self.memos = MemoRepository(session)
        self.perspectives = PerspectiveTaskRepository(session)
        self.reports = AnalysisReportRepository(session)
        self.events = AnalysisEventService(self.analyses, AnalysisEventRepository(session))

    @contextmanager
    def _transaction(self):
        try:
            yield
            self.session.commit()
        except (InvalidAnalysisStateTransition, InvalidAnalysisStageTransition, InvalidPerspectiveStateTransition) as exc:
            self.session.rollback()
            raise InternalAPIError(exc.code, "Transition not allowed") from None
        except Exception:
            self.session.rollback()
            raise

    def _task(self, task_id: UUID, *, lock=False):
        task = self.analyses.get_by_id(task_id, for_update=lock)
        if task is None:
            raise AnalysisNotFound()
        return task

    @staticmethod
    def _active(task):
        if task.status in TERMINAL_ANALYSIS_STATUSES:
            raise InternalAPIError("ANALYSIS_NOT_ACTIVE", "Terminal analysis cannot be modified")

    def _check_secrets(self, value):
        # Reject configured secrets/connection strings in caller content; arbitrary external
        # secrets cannot be inferred. Callers must supply safe summaries and redacted outputs.
        known = [self.settings.internal_api_key.get_secret_value(), self.settings.jwt_secret_key.get_secret_value(),
                 self.settings.rabbitmq_url.get_secret_value(), self.settings.database_url]
        known = [secret for secret in known if len(secret) >= 8]

        def check(item):
            if isinstance(item, str) and any(secret in item for secret in known):
                raise InternalAPIError("SENSITIVE_INTERNAL_PAYLOAD", "Sensitive content is not accepted", 422)
            if isinstance(item, dict):
                for child in item.values():
                    check(child)
            elif isinstance(item, list):
                for child in item:
                    check(child)
        check(value)

    def _emit(self, task, event_type, payload):
        self.session.flush()
        return self.events.append_in_transaction(task.id, event_type, payload)

    @staticmethod
    def _status(task):
        return InternalStatusResponse(task_id=task.id, status=task.status, current_stage=task.current_stage,
            cancelled=task.status == S.CANCELLED, has_warnings=task.has_warnings)

    def get_context(self, task_id: UUID) -> AnalysisContextResponse:
        task = self._task(task_id)
        memo = self.memos.get_by_id(task.memo_id)
        if memo is None:
            raise InternalAPIError("ANALYSIS_CONTEXT_NOT_FOUND", "Analysis memo context not found", 404)
        version = self.memos.get_version(task.memo_id, task.base_memo_version)
        if version is None:
            raise MemoVersionNotFound()
        filing = FilingRepository(self.session).get_by_receipt_no(
            task.disclosure_receipt_no)
        return AnalysisContextResponse(task_id=task.id, requested_by=task.requested_by, status=task.status, current_stage=task.current_stage,
            memo=ContextMemo(id=memo.id, version=version.version, title=memo.title, content=version.content,
                content_hash=version.content_hash, original_filename=version.original_filename),
            disclosure_receipt_no=task.disclosure_receipt_no, corp_code=task.corp_code,
            company_name=task.company_name_snapshot, created_at=task.created_at,
            filing_type=filing.filing_type if filing else None,
            is_correction=filing.is_correction if filing else None,
            filing_title=filing.title if filing else None)

    def get_status(self, task_id: UUID) -> InternalStatusResponse:
        return self._status(self._task(task_id))

    def append_event(self, task_id: UUID, request: InternalEventRequest) -> AnalysisEventResponse:
        self._check_secrets(request.model_dump(mode="json"))
        with self._transaction():
            task = self._task(task_id, lock=True)
            self._active(task)
            if request.event_type in SERVER_EVENTS:
                raise InternalAPIError("SERVER_OWNED_EVENT", "This event is emitted by server workflows")
            if request.event_type == E.ANALYSIS_WARNING:
                task.has_warnings = True
            result = self._emit(task, request.event_type, request.payload.model_dump(mode="json", exclude_none=True))
        return result

    def update_state(self, task_id: UUID, request: InternalStateRequest) -> InternalStatusResponse:
        self._check_secrets(request.model_dump(mode="json"))
        with self._transaction():
            task = self._task(task_id, lock=True)
            self._active(task)
            if request.status in (S.COMPLETED, S.COMPLETED_WITH_WARNINGS):
                raise InternalAPIError("REPORT_REQUIRED", "Completion is performed by report persistence")
            before = task.status
            if request.status is not None:
                transition_analysis(task, request.status)
            if request.stage is not None:
                # A status transition can already set its matching initial/save stage.
                if request.status is None or request.stage != task.current_stage:
                    advance_analysis_stage(task, request.stage)
            task.has_warnings = task.has_warnings or bool(request.has_warnings)
            if request.status in (S.FAILED, S.SAVE_FAILED):
                task.error_stage = request.error_stage or task.current_stage
                task.error_code = request.error_code or ("REPORT_SAVE_FAILED" if request.status == S.SAVE_FAILED else "ANALYSIS_FAILED")
                task.error_message = request.error_message or "Analysis execution failed"
            if task.status != before and task.status in STATUS_EVENTS:
                payload = {"status": task.status, "stage": task.current_stage}
                if task.status in (S.FAILED, S.SAVE_FAILED):
                    payload["code"] = task.error_code
                self._emit(task, STATUS_EVENTS[task.status], payload)
            result = self._status(task)
        return result

    def register_perspective(self, task_id: UUID, request: PerspectiveCreateRequest) -> PerspectiveResponse:
        self._check_secrets(request.model_dump(mode="json"))
        with self._transaction():
            task = self._task(task_id, lock=True)
            self._active(task)
            row = self.perspectives.get_by_analysis_task_and_type(task.id, request.perspective_type)
            if row is None:
                if task.status != S.RUNNING:
                    raise InternalAPIError("ANALYSIS_NOT_RUNNING", "Perspective registration requires RUNNING")
                row = self.perspectives.add(AnalysisPerspectiveTask(analysis_task_id=task.id,
                    **request.model_dump(), status=P.REGISTERED))
                self._emit(task, E.PERSPECTIVE_SELECTED, {"perspective": row.perspective_type,
                    "reason": row.selection_reason[:1000]})
            result = PerspectiveResponse.model_validate(row)
        return result

    def update_perspective(self, task_id: UUID, perspective_id: UUID, request: PerspectiveUpdateRequest) -> PerspectiveResponse:
        self._check_secrets(request.model_dump(mode="json"))
        with self._transaction():
            task = self._task(task_id, lock=True)
            self._active(task)
            if task.status != S.RUNNING:
                raise InternalAPIError("ANALYSIS_NOT_RUNNING", "Perspective execution requires RUNNING")
            row = self.perspectives.get_by_id_and_analysis_task(perspective_id, task.id)
            if row is None:
                raise InternalAPIError("PERSPECTIVE_NOT_FOUND", "Perspective not found for analysis", 404)
            transition_perspective(row, request.status)
            if request.result is not None:
                row.result_json = request.result
            row.failure_code, row.failure_message = request.failure_code, request.failure_message
            if row.status in (P.FAILED, P.INSUFFICIENT_EVIDENCE, P.LIMIT_REACHED):
                task.has_warnings = True
            event = E.PERSPECTIVE_STARTED if row.status == P.RUNNING else E.PERSPECTIVE_COMPLETED if row.status == P.COMPLETED else E.PERSPECTIVE_FAILED
            payload = {"perspective": row.perspective_type}
            if event == E.PERSPECTIVE_FAILED:
                payload["code"] = row.failure_code or row.status.value
            self._emit(task, event, payload)
            result = PerspectiveResponse.model_validate(row)
        return result

    @staticmethod
    def _report_response(task, report):
        return ReportSavedResponse(report_id=report.id, task_id=task.id, status=task.status,
            has_warnings=report.has_warnings, generated_at=report.generated_at, saved_at=report.saved_at)

    @staticmethod
    def _report_allowed(task):
        if task.status in (S.CANCELLED, S.FAILED):
            raise InternalAPIError("REPORT_NOT_ALLOWED", "Report cannot be saved for this analysis")

    def _prepare_report(self, task_id, request):
        with self._transaction():
            task = self._task(task_id, lock=True)
            self._report_allowed(task)
            existing = self.reports.get_by_analysis_task(task.id)
            if existing is not None:
                return self._report_response(task, existing)
            if task.status in (S.RUNNING, S.SAVE_FAILED):
                transition_analysis(task, S.SAVING)
                task.error_stage = task.error_code = task.error_message = None
                self._emit(task, E.REPORT_SAVE_STARTED, {"status": S.SAVING, "stage": G.REPORT_SAVE})
            elif task.status != S.SAVING or task.current_stage != G.REPORT_SAVE:
                raise InternalAPIError("REPORT_NOT_ALLOWED", "Report requires REPORT_GENERATION or REPORT_SAVE")
            task.has_warnings = task.has_warnings or request.has_warnings
        return None

    def _write_report(self, task_id, request):
        with self._transaction():
            task = self._task(task_id, lock=True)
            self._report_allowed(task)
            existing = self.reports.get_by_analysis_task(task.id)
            if existing is not None:
                return self._report_response(task, existing)
            if task.status != S.SAVING or task.current_stage != G.REPORT_SAVE:
                raise InternalAPIError("REPORT_NOT_ALLOWED", "Report persistence requires SAVING")
            warning = task.has_warnings or request.has_warnings
            now = utc_timestamp()
            report = self.reports.add(AnalysisReport(analysis_task_id=task.id, content=request.content,
                report_json=request.report, has_warnings=warning,
                no_additional_analysis_reason=request.no_additional_analysis_reason, generated_at=now, saved_at=now))
            task.has_warnings = warning
            transition_analysis(task, S.COMPLETED_WITH_WARNINGS if warning else S.COMPLETED)
            task.error_stage = task.error_code = task.error_message = None
            self._emit(task, E.REPORT_SAVED, {"status": task.status, "stage": G.REPORT_SAVE})
            self._emit(task, E.ANALYSIS_COMPLETED, {"status": task.status})
            result = self._report_response(task, report)
        return result

    def _record_save_failure(self, task_id):
        try:
            with self._transaction():
                task = self._task(task_id, lock=True)
                existing = self.reports.get_by_analysis_task(task.id)
                if existing is not None and task.status not in (S.CANCELLED, S.FAILED):
                    return self._report_response(task, existing)
                # Never overwrite cancellation, worker progress, or a terminal result.
                if task.status == S.RUNNING and task.current_stage == G.REPORT_GENERATION:
                    transition_analysis(task, S.SAVING)
                if task.status == S.SAVING:
                    transition_analysis(task, S.SAVE_FAILED)
                    task.error_stage = G.REPORT_SAVE
                    task.error_code = "REPORT_SAVE_FAILED"
                    task.error_message = "Report persistence failed; retry the same payload"
                    self._emit(task, E.REPORT_SAVE_FAILED, {"status": S.SAVE_FAILED, "code": "REPORT_SAVE_FAILED"})
        except (SQLAlchemyError, InternalAPIError):
            # If the DB is unavailable even this marker cannot be guaranteed. No payload
            # is durable here; caller retains the original report until confirmed saved.
            return None
        return None

    def save_report(self, task_id: UUID, request: ReportSaveRequest) -> ReportSavedResponse:
        self._check_secrets(request.model_dump(mode="json"))
        for attempt in range(self.settings.internal_report_save_max_attempts):
            try:
                existing = self._prepare_report(task_id, request)
                if existing is not None:
                    return existing
                return self._write_report(task_id, request)
            except SQLAlchemyError:
                # Separate DB retry from RabbitMQ producer/consumer retry.
                if attempt + 1 < self.settings.internal_report_save_max_attempts:
                    self.sleep(0.1 * 2 ** attempt)
        recovered = self._record_save_failure(task_id)
        if recovered is not None:
            return recovered
        raise InternalAPIError("REPORT_SAVE_FAILED", "Report save failed; retry the same payload", 503) from None
