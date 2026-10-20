from datetime import datetime, timedelta, timezone

import pytest

from app.domain.analysis_state_machine import (
    ACTIVE_ANALYSIS_STATUSES, TERMINAL_ANALYSIS_STATUSES,
    advance_analysis_stage, transition_analysis,
)
from app.domain.exceptions import (
    InvalidAnalysisStageTransition, InvalidAnalysisStateTransition,
    InvalidPerspectiveStateTransition,
)
from app.domain.perspective_state_machine import transition_perspective
from app.models import AnalysisPerspectiveTask, AnalysisTask
from app.models.enums import AnalysisStage as G, AnalysisStatus as S, PerspectiveStatus as P

NOW = datetime(2026, 10, 20, 6, 0, tzinfo=timezone.utc)
EARLIER = NOW - timedelta(minutes=10)
ALLOWED = [
    (S.CREATED, S.QUEUED), (S.QUEUED, S.RUNNING), (S.QUEUED, S.FAILED),
    (S.RUNNING, S.SAVING), (S.RUNNING, S.FAILED), (S.RUNNING, S.CANCELLED),
    (S.SAVING, S.COMPLETED), (S.SAVING, S.COMPLETED_WITH_WARNINGS),
    (S.SAVING, S.SAVE_FAILED), (S.SAVING, S.CANCELLED),
    (S.SAVE_FAILED, S.SAVING), (S.SAVE_FAILED, S.CANCELLED),
    (S.CREATED, S.CANCELLED), (S.QUEUED, S.CANCELLED),
]


def task(status, stage=None):
    if stage is None and status == S.RUNNING:
        stage = G.REPORT_GENERATION
    if stage is None and status in (S.SAVING, S.SAVE_FAILED):
        stage = G.REPORT_SAVE
    return AnalysisTask(status=status, current_stage=stage, started_at=None, completed_at=None, has_warnings=False)


@pytest.mark.parametrize("source,target", ALLOWED)
def test_allowed_analysis_transitions(source, target):
    item = task(source)
    assert transition_analysis(item, target, now=NOW) is item
    assert item.status is target
    if target in TERMINAL_ANALYSIS_STATUSES:
        assert item.completed_at == NOW
    else:
        assert item.completed_at is None


@pytest.mark.parametrize("source,target", [(a, b) for a in S for b in S if (a, b) not in ALLOWED])
def test_all_other_analysis_transitions_rejected(source, target):
    item = task(source)
    before = item.status, item.current_stage, item.started_at, item.completed_at
    with pytest.raises(InvalidAnalysisStateTransition) as error:
        transition_analysis(item, target, now=NOW)
    assert error.value.current_status == source
    assert error.value.target_status == target
    assert error.value.code == "INVALID_ANALYSIS_STATE"
    assert (item.status, item.current_stage, item.started_at, item.completed_at) == before


def test_running_timestamp_and_initial_stage():
    item = task(S.QUEUED)
    transition_analysis(item, S.RUNNING, now=NOW)
    assert item.started_at == NOW
    assert item.current_stage is G.REQUEST_VALIDATION
    other = task(S.QUEUED)
    other.started_at = EARLIER
    transition_analysis(other, S.RUNNING, now=NOW)
    assert other.started_at == EARLIER


def test_save_failed_retry_keeps_analysis_and_clears_nonterminal_completion():
    item = task(S.SAVING)
    item.started_at = EARLIER
    item.has_warnings = True
    item.error_code = "DB_UNAVAILABLE"
    transition_analysis(item, S.SAVE_FAILED, now=NOW)
    assert item.completed_at is None
    # Also clear an inconsistent old completion value when retrying.
    item.completed_at = EARLIER
    transition_analysis(item, S.SAVING, now=NOW)
    assert item.started_at == EARLIER
    assert item.completed_at is None
    assert item.current_stage is G.REPORT_SAVE
    assert item.error_code == "DB_UNAVAILABLE"
    assert item.has_warnings


@pytest.mark.parametrize("target", [S.COMPLETED, S.COMPLETED_WITH_WARNINGS])
def test_service_selects_completion_without_warning_classification(target):
    item = task(S.SAVING)
    item.has_warnings = True
    transition_analysis(item, target, now=NOW)
    assert item.status is target
    assert item.has_warnings is True


STAGE_EDGES = [
    (G.REQUEST_VALIDATION, G.INPUT_COLLECTION),
    (G.INPUT_COLLECTION, G.RAG_PREPARATION),
    (G.RAG_PREPARATION, G.BASE_ANALYSIS),
    (G.BASE_ANALYSIS, G.PERSPECTIVE_ANALYSIS),
    (G.PERSPECTIVE_ANALYSIS, G.REPORT_GENERATION),
    (G.BASE_ANALYSIS, G.REPORT_GENERATION),
    (G.REPORT_GENERATION, G.REPORT_SAVE),
    (G.INPUT_COLLECTION, G.REPORT_GENERATION),
    (G.RAG_PREPARATION, G.REPORT_GENERATION),
]


@pytest.mark.parametrize("source,target", STAGE_EDGES)
def test_forward_and_fallback_stage_edges(source, target):
    item = task(S.RUNNING, source)
    advance_analysis_stage(item, target, now=NOW)
    assert item.current_stage is target
    assert item.status is (S.SAVING if target == G.REPORT_SAVE else S.RUNNING)


@pytest.mark.parametrize("source,target", [
    (G.REPORT_GENERATION, G.BASE_ANALYSIS), (G.REPORT_SAVE, G.INPUT_COLLECTION),
    (G.REQUEST_VALIDATION, G.REPORT_GENERATION), (G.BASE_ANALYSIS, G.BASE_ANALYSIS),
    (None, G.BASE_ANALYSIS),
])
def test_invalid_stage_edges(source, target):
    item = task(S.RUNNING)
    item.current_stage = source
    with pytest.raises(InvalidAnalysisStageTransition) as error:
        advance_analysis_stage(item, target, now=NOW)
    assert error.value.code == "INVALID_ANALYSIS_STAGE"
    assert error.value.current_stage == source
    assert error.value.target_stage == target
    assert item.current_stage == source
    assert item.status is S.RUNNING


@pytest.mark.parametrize("status", [S.CREATED, S.QUEUED, S.RUNNING])
def test_stage_can_initialize_request_validation(status):
    item = task(status)
    item.current_stage = None
    advance_analysis_stage(item, G.REQUEST_VALIDATION)
    assert item.current_stage is G.REQUEST_VALIDATION


@pytest.mark.parametrize("status", [S.CREATED, S.QUEUED, S.SAVING, S.SAVE_FAILED, *TERMINAL_ANALYSIS_STATUSES])
def test_nonrunning_cannot_advance_processing(status):
    item = task(status, G.INPUT_COLLECTION)
    with pytest.raises(InvalidAnalysisStageTransition):
        advance_analysis_stage(item, G.RAG_PREPARATION)
    assert item.current_stage is G.INPUT_COLLECTION


def test_running_cannot_enter_saving_before_report_generation():
    item = task(S.RUNNING, G.BASE_ANALYSIS)
    with pytest.raises(InvalidAnalysisStageTransition):
        transition_analysis(item, S.SAVING, now=NOW)
    assert item.status is S.RUNNING
    assert item.current_stage is G.BASE_ANALYSIS
    assert item.completed_at is None


@pytest.mark.parametrize("source", list(ACTIVE_ANALYSIS_STATUSES))
def test_cancellation_even_with_unknown_legacy_stage(source):
    item = task(source)
    item.current_stage = None
    transition_analysis(item, S.CANCELLED, now=NOW)
    assert item.completed_at == NOW


@pytest.mark.parametrize("target", [P.COMPLETED, P.INSUFFICIENT_EVIDENCE, P.LIMIT_REACHED, P.FAILED])
def test_perspective_lifecycle(target):
    item = AnalysisPerspectiveTask(status=P.REGISTERED)
    transition_perspective(item, P.RUNNING, now=EARLIER)
    assert item.started_at == EARLIER
    assert item.completed_at is None
    transition_perspective(item, target, now=NOW)
    assert item.completed_at == NOW
    assert item.started_at == EARLIER
    assert item.status is target


@pytest.mark.parametrize("source,target", [(a, b) for a in P for b in P if not (a == P.REGISTERED and b == P.RUNNING) and not (a == P.RUNNING and b in (P.COMPLETED, P.INSUFFICIENT_EVIDENCE, P.LIMIT_REACHED, P.FAILED))])
def test_invalid_perspective_transitions(source, target):
    item = AnalysisPerspectiveTask(status=source)
    with pytest.raises(InvalidPerspectiveStateTransition) as error:
        transition_perspective(item, target, now=NOW)
    assert error.value.code == "INVALID_PERSPECTIVE_STATE"
    assert error.value.current_status == source
    assert error.value.target_status == target
    assert item.status == source
    assert item.started_at is None and item.completed_at is None


def test_naive_timestamps_rejected_before_mutation():
    item = task(S.QUEUED)
    with pytest.raises(ValueError, match="timezone-aware"):
        transition_analysis(item, S.RUNNING, now=datetime(2026, 10, 20))
    assert item.status is S.QUEUED
    other = AnalysisPerspectiveTask(status=P.REGISTERED)
    with pytest.raises(ValueError, match="timezone-aware"):
        transition_perspective(other, P.RUNNING, now=datetime(2026, 10, 20))
    assert other.status is P.REGISTERED


def test_timestamp_offsets_normalize_to_utc():
    item = task(S.QUEUED)
    transition_analysis(item, S.RUNNING, now=NOW.astimezone(timezone(timedelta(hours=9))))
    assert item.started_at == NOW
    assert item.started_at.tzinfo is timezone.utc
