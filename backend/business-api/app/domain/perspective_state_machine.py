from datetime import datetime

from app.domain.clock import utc_timestamp
from app.domain.exceptions import InvalidPerspectiveStateTransition
from app.models import AnalysisPerspectiveTask
from app.models.enums import PerspectiveStatus as Status

TERMINAL_PERSPECTIVE_STATUSES = frozenset({Status.COMPLETED, Status.INSUFFICIENT_EVIDENCE, Status.LIMIT_REACHED, Status.FAILED})
ACTIVE_PERSPECTIVE_STATUSES = frozenset({Status.REGISTERED, Status.RUNNING})
_TRANSITIONS = {Status.REGISTERED: frozenset({Status.RUNNING}), Status.RUNNING: TERMINAL_PERSPECTIVE_STATUSES}


def transition_perspective(task: AnalysisPerspectiveTask, target_status: Status, *, now: datetime | None = None) -> AnalysisPerspectiveTask:
    """Tool request/resume cycles leave RUNNING unchanged and do not call this function."""
    target_status = Status(target_status)
    if target_status not in _TRANSITIONS.get(task.status, ()):
        raise InvalidPerspectiveStateTransition(task.status, target_status)
    timestamp = utc_timestamp(now)
    task.status = target_status
    if target_status == Status.RUNNING:
        if task.started_at is None:
            task.started_at = timestamp
        task.completed_at = None
    else:
        task.completed_at = timestamp
    return task
