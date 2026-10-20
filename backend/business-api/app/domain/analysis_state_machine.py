from datetime import datetime

from app.domain.clock import utc_timestamp
from app.domain.exceptions import InvalidAnalysisStageTransition, InvalidAnalysisStateTransition
from app.models import AnalysisTask
from app.models.enums import AnalysisStage as Stage, AnalysisStatus as Status

TERMINAL_ANALYSIS_STATUSES = frozenset({Status.COMPLETED, Status.COMPLETED_WITH_WARNINGS, Status.FAILED, Status.CANCELLED})
ACTIVE_ANALYSIS_STATUSES = frozenset({Status.CREATED, Status.QUEUED, Status.RUNNING, Status.SAVING, Status.SAVE_FAILED})

_STATUS_TRANSITIONS = {
    Status.CREATED: frozenset({Status.QUEUED, Status.CANCELLED}),
    Status.QUEUED: frozenset({Status.RUNNING, Status.FAILED, Status.CANCELLED}),
    Status.RUNNING: frozenset({Status.SAVING, Status.FAILED, Status.CANCELLED}),
    Status.SAVING: frozenset({Status.COMPLETED, Status.COMPLETED_WITH_WARNINGS, Status.SAVE_FAILED, Status.CANCELLED}),
    Status.SAVE_FAILED: frozenset({Status.SAVING, Status.CANCELLED}),
}
_STAGE_TRANSITIONS = {
    None: frozenset({Stage.REQUEST_VALIDATION}),
    Stage.REQUEST_VALIDATION: frozenset({Stage.INPUT_COLLECTION}),
    Stage.INPUT_COLLECTION: frozenset({Stage.RAG_PREPARATION, Stage.REPORT_GENERATION}),
    Stage.RAG_PREPARATION: frozenset({Stage.BASE_ANALYSIS, Stage.REPORT_GENERATION}),
    Stage.BASE_ANALYSIS: frozenset({Stage.PERSPECTIVE_ANALYSIS, Stage.REPORT_GENERATION}),
    Stage.PERSPECTIVE_ANALYSIS: frozenset({Stage.REPORT_GENERATION}),
    Stage.REPORT_GENERATION: frozenset({Stage.REPORT_SAVE}),
}


def transition_analysis(task: AnalysisTask, target_status: Status, *, now: datetime | None = None) -> AnalysisTask:
    """Validate first, then mutate in memory. Caller owns locking, flush and transaction.

    No warning classification, retry execution, event insertion, or database IO occurs.
    """
    target_status = Status(target_status)
    current = task.status
    if target_status not in _STATUS_TRANSITIONS.get(current, ()):
        raise InvalidAnalysisStateTransition(current, target_status)

    next_stage = task.current_stage
    if target_status == Status.RUNNING:
        if next_stage not in (None, Stage.REQUEST_VALIDATION):
            raise InvalidAnalysisStageTransition(next_stage, Stage.REQUEST_VALIDATION, current)
        next_stage = Stage.REQUEST_VALIDATION
    elif target_status == Status.SAVING:
        required = Stage.REPORT_SAVE if current == Status.SAVE_FAILED else Stage.REPORT_GENERATION
        if next_stage != required:
            raise InvalidAnalysisStageTransition(next_stage, required, current)
        next_stage = Stage.REPORT_SAVE
    elif target_status != Status.CANCELLED and current in (Status.SAVING, Status.SAVE_FAILED) and next_stage != Stage.REPORT_SAVE:
        raise InvalidAnalysisStageTransition(next_stage, Stage.REPORT_SAVE, current)

    timestamp = utc_timestamp(now)
    task.status = target_status
    task.current_stage = next_stage
    if target_status == Status.RUNNING and task.started_at is None:
        task.started_at = timestamp
    # SAVE_FAILED is non-terminal; retry keeps started_at and REPORT_SAVE intact.
    task.completed_at = timestamp if target_status in TERMINAL_ANALYSIS_STATUSES else None
    return task


def advance_analysis_stage(task: AnalysisTask, target_stage: Stage, *, now: datetime | None = None) -> AnalysisTask:
    """Allow forward/fallback paths; entering REPORT_SAVE also enters SAVING atomically."""
    target_stage = Stage(target_stage)
    current = task.current_stage
    if target_stage not in _STAGE_TRANSITIONS.get(current, ()):
        raise InvalidAnalysisStageTransition(current, target_stage, task.status)
    if target_stage == Stage.REPORT_SAVE:
        if task.status != Status.RUNNING:
            raise InvalidAnalysisStageTransition(current, target_stage, task.status)
        return transition_analysis(task, Status.SAVING, now=now)
    if task.status != Status.RUNNING:
        # Request validation may be recorded before enqueue/worker startup.
        if task.status not in (Status.CREATED, Status.QUEUED) or target_stage != Stage.REQUEST_VALIDATION:
            raise InvalidAnalysisStageTransition(current, target_stage, task.status)
    task.current_stage = target_stage
    return task
